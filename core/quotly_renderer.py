"""
引用消息渲染器 - 使用 Playwright 渲染 HTML
QQ 聊天气泡样式 1:1 复刻
"""

import asyncio
import base64
from pathlib import Path
from typing import List, Optional
from astrbot.api import logger


class QuotlyRenderer:
    """引用消息渲染器"""
    
    _playwright = None
    _browser = None
    _lock = asyncio.Lock()

    def __init__(self, font_dir: Optional[str] = None):
        """
        初始化渲染器

        Args:
            font_dir: 字体目录路径，默认为 assets/fonts/
        """
        if font_dir is None:
            plugin_dir = Path(__file__).parent.parent
            font_dir = plugin_dir / "assets" / "fonts"

        self.font_dir = Path(font_dir)
        
        # 优先使用鸿蒙字体，如果不存在则使用思源黑体
        font_path = self.font_dir / "HarmonyOS_Sans_SC_Regular.ttf"
        if font_path.exists():
            self.font_name = "HarmonyOS Sans SC"
            self.font_format = "truetype"
        else:
            font_path = self.font_dir / "SourceHanSansCN-Regular.otf"
            self.font_name = "SourceHanSansCN"
            self.font_format = "opentype"

        # 读取字体文件并转为 base64
        with open(font_path, 'rb') as f:
            font_data = f.read()
        self.font_base64 = base64.b64encode(font_data).decode('ascii')

    async def _ensure_browser(self):
        """确保浏览器实例已启动"""
        async with self._lock:
            if self._browser is None:
                logger.debug("启动浏览器实例...")
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-gpu',
                        '--disable-gpu-compositing',
                        '--disable-software-rasterizer',
                    ]
                )
                logger.debug("浏览器实例已启动")

    async def cleanup(self):
        """清理浏览器实例"""
        async with self._lock:
            if self._browser is not None:
                logger.debug("关闭浏览器实例...")
                await self._browser.close()
                await self._playwright.stop()
                self._browser = None
                self._playwright = None
                logger.debug("浏览器实例已关闭")

    async def arender(self, messages: List[dict]) -> bytes:
        """
        异步渲染消息列表为 PNG 图片

        Args:
            messages: 消息列表，每条消息包含:
                - nickname: 发送者昵称
                - card: 群名片（可选）
                - title: 群头衔（可选）
                - user_id: QQ 号
                - content: 消息内容
                - time_str: 格式化的时间字符串
                - avatar_url: 头像 URL（可选）

        Returns:
            PNG 格式的字节数据
        """
        await self._ensure_browser()
        html_content = self._build_html(messages)
        
        # 使用全局浏览器实例创建新页面
        page = await self._browser.new_page(viewport={"width": 800, "height": 100})
        try:
            await page.set_content(html_content)
            # 等待 DOM 加载完成
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            # 等待字体和图片加载，以及 JavaScript 执行
            await page.wait_for_timeout(1000)
            
            # 使用 full_page=True 自动适应任意高度
            screenshot = await page.screenshot(
                full_page=True,
                type="png",
                animations="disabled",
                caret="initial"
            )
            return screenshot
        finally:
            await page.close()

    def render(self, messages: List[dict]) -> bytes:
        """
        同步渲染消息列表为 PNG 图片

        Args:
            messages: 消息列表

        Returns:
            PNG 格式的字节数据
        """
        return asyncio.run(self.arender(messages))

    def _build_html(self, messages: List[dict]) -> str:
        """构建 HTML 内容 - QQ 聊天气泡样式"""
        # 构建消息 HTML
        messages_html = ""
        for msg in messages:
            nickname = self._escape_html(msg.get('nickname', '未知用户'))
            card = msg.get('card', '')
            title = msg.get('title', '')  # 群头衔
            role = msg.get('role', 'member')  # 角色 (owner/admin/member)
            content = self._escape_html(msg.get('content', ''))
            time_str = self._escape_html(msg.get('time_str', ''))
            avatar_url = msg.get('avatar_url', '')

            # 头像 HTML
            if avatar_url:
                avatar_html = f'<img class="avatar" src="{avatar_url}" onerror="this.style.display=\'none\'">'
            else:
                avatar_html = f'<div class="avatar-placeholder">{nickname[0] if nickname else "?"}</div>'

            # 头部信息：群头衔 > 姓名 > 时间
            header_html = ""
            
            # 根据 role 和 title 决定头衔显示
            if role == "owner":
                # 群主：显示"群主"，金色背景
                header_html += '<span class="title-owner">群主</span>'
            elif role == "admin":
                # 管理员：显示专属头衔或"管理"，绿色背景
                display_title = title if title else "管理"
                header_html += f'<span class="title-admin">{display_title}</span>'
            elif title:
                # 普通成员有专属头衔：显示专属头衔，紫色背景
                header_html += f'<span class="title-special">{title}</span>'
            
            header_html += f'<span class="nickname">{card if card else nickname}</span>'
            if time_str:
                header_html += f'<span class="time">{time_str}</span>'

            # 处理消息内容，支持 [图片](url) 格式
            content_html = self._parse_content(content)

            # 消息气泡
            messages_html += f"""
            <div class="message left">
                <div class="avatar-wrapper">
                    {avatar_html}
                </div>
                <div class="content-wrapper">
                    <div class="message-header">{header_html}</div>
                    <div class="bubble">
                        <div class="message-content">{content_html}</div>
                    </div>
                </div>
            </div>
            """

        # 完整 HTML
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        @font-face {{
            font-family: '{self.font_name}';
            src: url('data:font/{self.font_format};base64,{self.font_base64}') format('{self.font_format}');
            font-weight: normal;
            font-style: normal;
            font-display: block;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: '{self.font_name}', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
            background: #e8e8ed;
            padding: 0;
            display: inline-flex;
            justify-content: center;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            text-rendering: optimizeLegibility;
        }}

        .chat-container {{
            width: fit-content;
            max-width: 1200px;
            min-width: 200px;
            background: #e8e8ed;
            padding: 30px;
        }}


        .message {{
            display: flex;
            margin: 32px 0;
            align-items: flex-start;
        }}

        .avatar-wrapper {{
            flex-shrink: 0;
        }}

        .avatar, .avatar-placeholder {{
            width: 100px;
            height: 100px;
            border-radius: 50%;
            object-fit: cover;
        }}

        .avatar-placeholder {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 36px;
            font-weight: 500;
        }}

        .content-wrapper {{
            margin-left: 24px;
            flex: 0 1 auto;
            min-width: 0;
        }}

        .message-header {{
            margin-bottom: 10px;
            font-size: 28px;
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }}

        .title-owner {{
            color: #b8860b;
            background: #fff9e6;
            padding: 4px 16px;
            border-radius: 8px;
            font-size: 24px;
        }}

        .title-admin {{
            color: #1a9f06;
            background: #e6f7e6;
            padding: 4px 16px;
            border-radius: 8px;
            font-size: 24px;
        }}

        .title-special {{
            color: #7b1fa2;
            background: #f3e5f5;
            padding: 4px 16px;
            border-radius: 8px;
            font-size: 24px;
        }}

        .nickname {{
            color: #888888;
            font-weight: 500;
        }}

        .time {{
            color: #999;
            font-size: 26px;
        }}

        /* 气泡样式 - 白色气泡，无箭头 */
        .bubble {{
            background: #ffffff;
            border-radius: 24px;
            padding: 16px 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            overflow-wrap: break-word;
            display: inline-block;
            width: fit-content;
        }}

        .message-content {{
            font-size: 32px;
            line-height: 1.6;
            color: #1a1a1a;
            white-space: pre-wrap;
            word-break: break-word;
            display: inline;
        }}

        .msg-image {{
            max-width: 100%;
            border-radius: 8px;
            margin-top: 5px;
        }}
    </style>
</head>
<body>
    <div class="chat-container">
        {messages_html}
    </div>
    <script>
    function adjustBubbleWidth() {{
        const bubbles = document.querySelectorAll('.bubble');
        bubbles.forEach(bubble => {{
            const content = bubble.querySelector('.message-content');
            if (!content) return;
            
            // 获取气泡实际需要的宽度
            const actualWidth = bubble.scrollWidth;
            const minWidth = 100; // 最小宽度
            const maxWidth = 1100; // 最大宽度（留出 padding）
            
            // 设置合适的宽度（限制在最小和最大宽度之间）
            const finalWidth = Math.min(Math.max(actualWidth, minWidth), maxWidth);
            bubble.style.width = finalWidth + 'px';
        }});
    }}
    
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', adjustBubbleWidth);
    }} else {{
        adjustBubbleWidth();
    }}
    </script>
</body>
</html>
        """
        return html

    def _escape_html(self, text: str) -> str:
        """转义 HTML 特殊字符"""
        if not text:
            return ""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

    def _parse_content(self, content: str) -> str:
        """
        解析消息内容，支持 [图片](url) 格式

        Args:
            content: 原始消息内容

        Returns:
            包含 HTML 标签的内容
        """
        import re

        # 转义 HTML 特殊字符
        escaped = self._escape_html(content)

        # 匹配 [图片](url) 格式
        pattern = r'\[图片\]\(([^)]+)\)'

        def replace_image(match):
            url = match.group(1)
            return f'<img class="msg-image" src="{url}" onerror="this.style.display=\'none\'">'

        # 替换图片标签，同时保留换行
        result = re.sub(pattern, replace_image, escaped)
        # 将换行符转换为 <br>
        result = result.replace('\n', '<br>')

        return result
