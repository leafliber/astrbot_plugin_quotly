"""
引用消息渲染器 - 使用 Playwright 渲染 HTML
QQ 聊天气泡样式 1:1 复刻
"""

import asyncio
import base64
from pathlib import Path
from typing import List, Optional


class QuotlyRenderer:
    """引用消息渲染器"""

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
        font_path = self.font_dir / "SourceHanSansCN-Regular.otf"

        # 读取字体文件并转为 base64
        with open(font_path, 'rb') as f:
            font_data = f.read()
        self.font_base64 = base64.b64encode(font_data).decode('ascii')

        # Playwright 相关
        self._playwright = None
        self._browser = None

    async def _get_browser(self):
        """获取或初始化浏览器实例"""
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
            )
        return self._browser

    async def _close_browser(self):
        """关闭浏览器"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

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
        html_content = self._build_html(messages)
        browser = await self._get_browser()

        page = await browser.new_page(viewport={"width": 400, "height": 100, "device_scale_factor": 2})
        try:
            await page.set_content(html_content)
            # 等待字体和图片加载
            await page.wait_for_load_state("networkidle", timeout=5000)
            await page.wait_for_timeout(500)
            screenshot = await page.screenshot(full_page=True)
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
            if title:
                # 根据头衔类型设置不同的样式类
                if "群主" in title:
                    title_class = "title-owner"
                elif "管理员" in title:
                    title_class = "title-admin"
                else:
                    title_class = "title-special"
                header_html += f'<span class="{title_class}">{title}</span>'
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
            font-family: 'SourceHanSansCN';
            src: url('data:font/otf;base64,{self.font_base64}');
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', 'Source Han Sans CN', sans-serif;
            background: #e8e8ed;
            padding: 0;
            display: flex;
            justify-content: center;
        }}

        .chat-container {{
            width: 380px;
            background: #e8e8ed;
            padding: 10px;
        }}


        .message {{
            display: flex;
            margin: 12px 0;
            align-items: flex-start;
        }}

        .message {{
            display: flex;
            margin: 12px 0;
            align-items: flex-start;
        }}

        .avatar-wrapper {{
            flex-shrink: 0;
        }}

        .avatar, .avatar-placeholder {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            object-fit: cover;
        }}

        .avatar-placeholder {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 15px;
            font-weight: 500;
        }}

        .content-wrapper {{
            margin-left: 10px;
            max-width: 100%;
        }}

        .message-header {{
            margin-bottom: 4px;
            font-size: 12px;
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 4px;
        }}

        .title-owner {{
            color: #b8860b;
            background: #fff9e6;
            padding: 1px 6px;
            border-radius: 3px;
            font-size: 11px;
        }}

        .title-admin {{
            color: #1a9f06;
            background: #e6f7e6;
            padding: 1px 6px;
            border-radius: 3px;
            font-size: 11px;
        }}

        .title-special {{
            color: #7b1fa2;
            background: #f3e5f5;
            padding: 1px 6px;
            border-radius: 3px;
            font-size: 11px;
        }}

        .nickname {{
            color: #888888;
            font-weight: 500;
        }}

        .time {{
            color: #999;
            font-size: 11px;
        }}

        /* 气泡样式 - 白色气泡，无箭头 */
        .bubble {{
            background: #ffffff;
            border-radius: 10px;
            padding: 8px 12px;
            box-shadow: 0 1px 1px rgba(0,0,0,0.08);
            word-wrap: break-word;
        }}

        .message-content {{
            font-size: 14px;
            line-height: 1.5;
            color: #1a1a1a;
            white-space: pre-wrap;
            word-break: break-word;
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

    async def close(self):
        """关闭渲染器，释放资源"""
        await self._close_browser()
