"""
引用消息渲染器 - 使用 Playwright 渲染 HTML
QQ 聊天气泡样式 1:1 复刻
"""

import asyncio
import base64
import pathlib
import time
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional
from astrbot.api import logger

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    HAS_ASTRBOT_PATH = True
except ImportError:
    HAS_ASTRBOT_PATH = False


FONT_DOWNLOAD_URLS = {
    "HarmonyOS_Sans_SC_Regular.ttf": "https://cdn.jsdelivr.net/gh/IKKI2000/harmonyos-fonts@latest/fonts/HarmonyOS_Sans_SC/HarmonyOS_Sans_SC_Regular.ttf",
    "HarmonyOS_Sans_SC_Medium.ttf": "https://cdn.jsdelivr.net/gh/IKKI2000/harmonyos-fonts@latest/fonts/HarmonyOS_Sans_SC/HarmonyOS_Sans_SC_Medium.ttf",
    "HarmonyOS_Sans_SC_Bold.ttf": "https://cdn.jsdelivr.net/gh/IKKI2000/harmonyos-fonts@latest/fonts/HarmonyOS_Sans_SC/HarmonyOS_Sans_SC_Bold.ttf",
}

PAGE_POOL_SIZE = 3
AVATAR_CACHE_SIZE = 200


class LRUCache:
    """简单的 LRU 缓存实现"""
    
    def __init__(self, max_size: int):
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[bytes]:
        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None
    
    async def set(self, key: str, value: bytes):
        async with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.max_size:
                    self.cache.popitem(last=False)
                self.cache[key] = value


class QuotlyRenderer:
    """引用消息渲染器"""
    
    _global_lock = asyncio.Lock()
    _instance_count = 0
    _font_base64_cache: Optional[str] = None
    _fonts_checked = False
    _font_lock = asyncio.Lock()
    _avatar_cache: Optional[LRUCache] = None

    def __init__(self):
        """
        初始化渲染器
        """
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._initialized = False
        self._page_pool: asyncio.Queue = asyncio.Queue(maxsize=PAGE_POOL_SIZE)
        self._page_pool_initialized = False
        self._page_pool_lock = asyncio.Lock()
        
        if HAS_ASTRBOT_PATH:
            data_path = get_astrbot_data_path()
            data_dir = (pathlib.Path(data_path) if isinstance(data_path, str)
                       else data_path) / "plugin_data" / "astrbot_plugin_quotly"
        else:
            data_dir = Path(__file__).parent.parent / "data"
        
        self._fonts_dir = data_dir / "fonts"
        self._fonts_dir.mkdir(parents=True, exist_ok=True)
        
        if QuotlyRenderer._avatar_cache is None:
            QuotlyRenderer._avatar_cache = LRUCache(AVATAR_CACHE_SIZE)
        
        QuotlyRenderer._instance_count += 1
        logger.debug(f"QuotlyRenderer 实例创建，当前实例数: {QuotlyRenderer._instance_count}")

    async def ensure_fonts(self):
        """
        确保字体文件存在，如果不存在则自动下载
        可在插件启动时调用，提前下载字体
        """
        if QuotlyRenderer._fonts_checked:
            return
        
        async with QuotlyRenderer._font_lock:
            if QuotlyRenderer._fonts_checked:
                return
            
            missing_fonts = []
            for font_file in FONT_DOWNLOAD_URLS:
                font_path = self._fonts_dir / font_file
                if not font_path.exists():
                    missing_fonts.append(font_file)
            
            if not missing_fonts:
                logger.debug("所有字体文件已存在")
                QuotlyRenderer._fonts_checked = True
                self._get_font_base64()
                return
            
            logger.info(f"正在下载缺失的字体文件: {missing_fonts}")
            
            import aiohttp
            downloaded = False
            try:
                async with aiohttp.ClientSession() as session:
                    download_tasks = []
                    for font_file in missing_fonts:
                        download_tasks.append(self._download_font(session, font_file))
                    
                    results = await asyncio.gather(*download_tasks, return_exceptions=True)
                    downloaded = any(r for r in results if r is True)
            except Exception as e:
                logger.error(f"字体下载过程出错: {e}")
            
            if downloaded:
                QuotlyRenderer._font_base64_cache = None
            
            all_exist = all((self._fonts_dir / f).exists() for f in FONT_DOWNLOAD_URLS)
            if all_exist:
                QuotlyRenderer._fonts_checked = True
                self._get_font_base64()
                logger.info("字体加载完成")

    async def _download_font(self, session, font_file: str) -> bool:
        """下载单个字体文件"""
        url = FONT_DOWNLOAD_URLS[font_file]
        font_path = self._fonts_dir / font_file
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                if resp.status == 200:
                    font_data = await resp.read()
                    with open(font_path, "wb") as f:
                        f.write(font_data)
                    logger.info(f"字体下载成功: {font_file}")
                    return True
                else:
                    logger.warning(f"字体下载失败: {font_file}, HTTP {resp.status}")
        except Exception as e:
            logger.warning(f"字体下载失败: {font_file}, 错误: {e}")
        return False

    def _get_font_base64(self) -> Optional[str]:
        """
        获取本地字体的 base64 编码（带缓存）
        
        Returns:
            字体的 base64 data URI，如果字体不存在则返回 None
        """
        if QuotlyRenderer._font_base64_cache is not None:
            return QuotlyRenderer._font_base64_cache
        
        font_weight_map = {
            "HarmonyOS_Sans_SC_Regular.ttf": "font-weight: 400;",
            "HarmonyOS_Sans_SC_Medium.ttf": "font-weight: 500;",
            "HarmonyOS_Sans_SC_Bold.ttf": "font-weight: 700;",
        }
        
        font_faces = []
        has_local_font = False
        
        for font_file, url in FONT_DOWNLOAD_URLS.items():
            font_path = self._fonts_dir / font_file
            if font_path.exists():
                try:
                    with open(font_path, "rb") as f:
                        font_data = f.read()
                    font_base64 = base64.b64encode(font_data).decode("utf-8")
                    weight_style = font_weight_map.get(font_file, "font-weight: 400;")
                    font_faces.append(f"""
        @font-face {{
            font-family: 'HarmonyOS Sans SC';
            src: url(data:font/ttf;base64,{font_base64}) format('truetype');
            {weight_style}
            font-display: swap;
        }}""")
                    has_local_font = True
                    logger.debug(f"已加载本地字体: {font_file}")
                except Exception as e:
                    logger.warning(f"读取字体文件失败 {font_file}: {e}")
        
        if has_local_font:
            QuotlyRenderer._font_base64_cache = "\n".join(font_faces)
            logger.info("使用本地 HarmonyOS Sans SC 字体")
            return QuotlyRenderer._font_base64_cache
        
        return None

    async def _ensure_browser(self):
        """确保浏览器实例已启动"""
        async with self._lock:
            if self._browser is None or not self._initialized:
                logger.debug("启动浏览器实例...")
                try:
                    from playwright.async_api import async_playwright
                    self._playwright = await async_playwright().start()
                    self._browser = await self._playwright.chromium.launch(
                        headless=True,
                        args=[
                            '--disable-gpu',
                            '--disable-gpu-compositing',
                            '--disable-software-rasterizer',
                            '--allow-file-access-from-files',
                            '--disable-dev-shm-usage',
                            '--no-sandbox',
                            '--disable-setuid-sandbox',
                        ]
                    )
                    self._initialized = True
                    logger.debug("浏览器实例已启动")
                    
                    await self._init_page_pool()
                except Exception as e:
                    logger.error(f"启动浏览器实例失败: {e}")
                    raise

    async def _init_page_pool(self):
        """初始化页面池"""
        async with self._page_pool_lock:
            if self._page_pool_initialized:
                return
            
            logger.debug(f"初始化页面池，大小: {PAGE_POOL_SIZE}")
            for i in range(PAGE_POOL_SIZE):
                try:
                    page = await self._browser.new_page(viewport={"width": 800, "height": 100})
                    await self._page_pool.put(page)
                except Exception as e:
                    logger.warning(f"创建页面 {i} 失败: {e}")
            
            self._page_pool_initialized = True
            logger.debug("页面池初始化完成")

    async def _get_page(self):
        """从页面池获取一个页面"""
        try:
            page = await asyncio.wait_for(self._page_pool.get(), timeout=5.0)
            return page
        except asyncio.TimeoutError:
            logger.debug("页面池为空，创建新页面")
            return await self._browser.new_page(viewport={"width": 800, "height": 100})

    async def _return_page(self, page):
        """将页面返回到页面池"""
        try:
            await page.goto("about:blank", timeout=2000)
            await self._page_pool.put(page)
        except Exception as e:
            logger.debug(f"页面返回池失败，关闭页面: {e}")
            try:
                await page.close()
            except:
                pass

    async def cleanup(self):
        """清理浏览器实例"""
        async with self._lock:
            while not self._page_pool.empty():
                try:
                    page = self._page_pool.get_nowait()
                    await page.close()
                except:
                    pass
            self._page_pool_initialized = False
            
            if self._browser is not None:
                logger.debug("关闭浏览器实例...")
                try:
                    await self._browser.close()
                    await self._playwright.stop()
                    self._browser = None
                    self._playwright = None
                    self._initialized = False
                    logger.debug("浏览器实例已关闭")
                except Exception as e:
                    logger.warning(f"关闭浏览器实例时出错: {e}")
                    self._browser = None
                    self._playwright = None
                    self._initialized = False
        
        QuotlyRenderer._instance_count = max(0, QuotlyRenderer._instance_count - 1)
        logger.debug(f"QuotlyRenderer 实例清理，当前实例数: {QuotlyRenderer._instance_count}")

    async def arender(self, messages: List[dict], show_title: bool = True, show_time: bool = True, show_date: bool = True) -> bytes:
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
                - type: 消息类型（可选，"date_separator" 表示日期分隔符）
            show_title: 是否显示群头衔
            show_time: 是否显示消息时间
            show_date: 是否显示日期分隔符

        Returns:
            PNG 格式的字节数据
        """
        start_time = time.time()
        
        await self._ensure_browser()
        
        avatar_urls = set()
        for msg in messages:
            if msg.get('type') != 'date_separator':
                avatar_url = msg.get('avatar_url', '')
                if avatar_url and not avatar_url.startswith('data:'):
                    avatar_urls.add(avatar_url)
        
        if avatar_urls:
            preload_tasks = [self._preload_avatar(url) for url in avatar_urls]
            await asyncio.gather(*preload_tasks, return_exceptions=True)
        
        html_content = await self._build_html_async(messages, show_title=show_title, show_time=show_time, show_date=show_date)
        
        page = await self._get_page()
        try:
            await page.set_content(html_content, wait_until="commit", timeout=30000)
            
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception as e:
                logger.debug(f"DOM 加载超时，继续渲染: {e}")
            
            try:
                await page.wait_for_function(
                    """() => {
                        const images = document.querySelectorAll('img');
                        if (images.length === 0) return true;
                        return Array.from(images).every(img => img.complete);
                    }""",
                    timeout=5000
                )
            except Exception as e:
                logger.debug(f"图片加载等待超时，继续渲染: {e}")
            
            screenshot = await page.screenshot(
                full_page=True,
                type="png",
                animations="disabled",
                caret="initial",
                timeout=30000
            )
            
            elapsed = time.time() - start_time
            logger.debug(f"渲染完成，耗时: {elapsed:.2f}秒")
            
            return screenshot
        finally:
            await self._return_page(page)

    async def _preload_avatar(self, url: str):
        """预加载并缓存头像"""
        if not url or url.startswith('data:'):
            return
        
        cached = await QuotlyRenderer._avatar_cache.get(url)
        if cached is not None:
            return
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await QuotlyRenderer._avatar_cache.set(url, data)
                        logger.debug(f"预加载头像缓存: {url[:50]}...")
        except Exception as e:
            logger.debug(f"预加载头像失败: {url[:50]}..., 错误: {e}")

    def render(self, messages: List[dict]) -> bytes:
        """
        同步渲染消息列表为 PNG 图片

        Args:
            messages: 消息列表

        Returns:
            PNG 格式的字节数据
        """
        return asyncio.run(self.arender(messages))

    async def _get_avatar_base64(self, url: str) -> str:
        """获取头像的 base64 数据"""
        if not url:
            return ""
        
        if url.startswith('data:'):
            return url
        
        cached = await QuotlyRenderer._avatar_cache.get(url)
        if cached:
            return f"data:image/png;base64,{base64.b64encode(cached).decode('utf-8')}"
        
        return url

    async def _build_html_async(self, messages: List[dict], show_title: bool = True, show_time: bool = True, show_date: bool = True) -> str:
        """构建 HTML 内容 - QQ 聊天气泡样式（异步版本，使用预加载的头像）"""
        messages_html = ""
        for msg in messages:
            if msg.get('type') == 'date_separator':
                if show_date:
                    date_str = self._escape_html(msg.get('date_str', ''))
                    messages_html += f'<div class="date-separator"><span class="date-text">{date_str}</span></div>\n'
                continue
            
            nickname = self._escape_html(msg.get('nickname', '未知用户'))
            card = msg.get('card', '')
            title = msg.get('title', '')
            role = msg.get('role', 'member')
            content = self._escape_html(msg.get('content', ''))
            time_str = self._escape_html(msg.get('time_str', ''))
            avatar_url = msg.get('avatar_url', '')
            reply_info = msg.get('reply_info')

            avatar_html = ""
            if avatar_url:
                avatar_base64 = await self._get_avatar_base64(avatar_url)
                if avatar_base64:
                    avatar_html = f'<img class="avatar" src="{avatar_base64}" onerror="this.style.display=\'none\'">'
            
            if not avatar_html:
                avatar_html = f'<div class="avatar-placeholder">{nickname[0] if nickname else "?"}</div>'

            header_html = ""
            
            if show_title:
                if role == "owner":
                    header_html += '<span class="title-owner">群主</span>'
                elif role == "admin":
                    display_title = title if title else "管理员"
                    header_html += f'<span class="title-admin">{display_title}</span>'
                elif title:
                    header_html += f'<span class="title-special">{title}</span>'
            
            header_html += f'<span class="nickname">{card if card else nickname}</span>'
            if show_time and time_str:
                header_html += f'<span class="time">{time_str}</span>'

            reply_html = ""
            if reply_info:
                reply_nickname = self._escape_html(reply_info.get('nickname', ''))
                reply_content = reply_info.get('content', '')
                reply_content_html, _ = self._parse_content(reply_content)
                reply_html = f'''
                <div class="reply-preview">
                    <div class="reply-header">
                        <span class="reply-arrow">↩</span>
                        <span class="reply-nickname">{reply_nickname}</span>
                    </div>
                    <div class="reply-content">{reply_content_html}</div>
                </div>'''

            is_image_only, image_url = self._is_image_only(content)
            bubble_class = "bubble"
            content_html = ""
            
            if is_image_only and not reply_html:
                bubble_class = "bubble image-only"
                content_html = f'<img class="msg-image-full" src="{image_url}" alt="[图片]" onerror="this.outerHTML=\'[图片]\'">'
            else:
                content_html_parsed, _ = self._parse_content(content)
                content_html = f'<div class="message-content">{content_html_parsed}</div>'

            messages_html += f"""
            <div class="message left">
                <div class="avatar-wrapper">
                    {avatar_html}
                </div>
                <div class="content-wrapper">
                    <div class="message-header">{header_html}</div>
                    <div class="{bubble_class}">
                        {reply_html}{content_html}
                    </div>
                </div>
            </div>
            """

        local_font_css = self._get_font_base64()
        
        font_cdn_links = ""
        if not local_font_css:
            font_cdn_links = """
    <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
    <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Regular/Regular.css" rel="stylesheet" media="print" onload="this.media='all'">
    <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Medium/Medium.css" rel="stylesheet" media="print" onload="this.media='all'">
    <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Bold/Bold.css" rel="stylesheet" media="print" onload="this.media='all'">
    <noscript>
        <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Regular/Regular.css" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Medium/Medium.css" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Bold/Bold.css" rel="stylesheet">
    </noscript>"""
        
        return self._build_html_template(messages_html, local_font_css, font_cdn_links)

    def _build_html_template(self, messages_html: str, local_font_css: str, font_cdn_links: str) -> str:
        """构建完整的 HTML 模板"""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">{font_cdn_links}
    <style>
        {local_font_css if local_font_css else ''}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'HarmonyOS Sans SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Helvetica Neue', sans-serif;
            background: #ebebf0;
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
            background: #ebebf0;
            padding: 30px;
        }}

        .date-separator {{
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 40px 0 20px 0;
            width: 100%;
        }}

        .date-separator:first-child {{
            margin-top: 0;
        }}

        .date-text {{
            color: #999;
            font-size: 26px;
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
            width: 80px;
            height: 80px;
            border-radius: 50%;
            object-fit: cover;
        }}

        .avatar-placeholder {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
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

        .bubble {{
            background: #ffffff;
            border-radius: 24px;
            padding: 16px 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            overflow-wrap: break-word;
            display: inline-block;
            width: fit-content;
            box-sizing: border-box;
        }}

        .message-content {{
            font-size: 32px;
            line-height: 1.6;
            color: #1a1a1a;
            white-space: pre-wrap;
            word-break: break-word;
            display: block;
        }}

        .msg-image {{
            max-width: 600px;
            min-width: 300px;
            width: auto;
            max-height: 800px;
            height: auto;
            border-radius: 8px;
            margin-top: 8px;
            display: block;
            object-fit: contain;
        }}

        .bubble.image-only {{
            padding: 0;
            overflow: hidden;
            line-height: 0;
        }}

        .msg-image-full {{
            display: block;
            max-width: 600px;
            min-width: 200px;
            width: auto;
            max-height: 800px;
            height: auto;
            border-radius: 24px;
            object-fit: cover;
        }}

        .reply-preview {{
            background: #f5f5f5;
            border-left: 3px solid #999;
            padding: 8px 12px;
            margin-bottom: 10px;
            border-radius: 4px;
            font-size: 26px;
            color: #666;
            display: block;
            max-width: 100%;
        }}

        .reply-header {{
            display: inline;
        }}

        .reply-arrow {{
            color: #999;
            margin-right: 6px;
        }}

        .reply-nickname {{
            color: #576b95;
            font-weight: 500;
            margin-right: 6px;
        }}

        .reply-content {{
            color: #666;
            margin-top: 4px;
        }}
        
        .reply-content .msg-image {{
            max-width: 150px;
            min-width: 50px;
            max-height: 80px;
            width: auto;
            height: auto;
            border-radius: 4px;
            vertical-align: middle;
            margin: 4px 0;
            display: block;
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
            if (bubble.classList.contains('image-only')) {{
                return;
            }}
            
            const content = bubble.querySelector('.message-content');
            const replyPreview = bubble.querySelector('.reply-preview');
            if (!content) return;
            
            const contentRange = document.createRange();
            contentRange.selectNodeContents(content);
            const contentRects = contentRange.getClientRects();
            
            let maxContentWidth = 0;
            if (contentRects.length > 0) {{
                for (let i = 0; i < contentRects.length; i++) {{
                    if (contentRects[i].width > maxContentWidth) {{
                        maxContentWidth = contentRects[i].width;
                    }}
                }}
            }} else {{
                maxContentWidth = content.scrollWidth;
            }}
            
            let replyWidth = 0;
            if (replyPreview) {{
                const originalMaxWidth = replyPreview.style.maxWidth;
                replyPreview.style.maxWidth = 'none';
                replyPreview.style.width = 'auto';
                replyWidth = replyPreview.scrollWidth;
                replyPreview.style.maxWidth = originalMaxWidth;
                replyPreview.style.width = '';
            }}
            
            const maxLineWidth = Math.ceil(Math.max(maxContentWidth, replyWidth));
            const extraPadding = 6;
            const minWidth = 100;
            const maxWidth = 1100;
            
            const finalWidth = Math.min(Math.max(maxLineWidth + 40 + extraPadding, minWidth), maxWidth);
            bubble.style.width = Math.ceil(finalWidth) + 'px';
        }});
    }}
    
    function waitForImagesAndAdjust() {{
        const images = document.querySelectorAll('.msg-image, .msg-image-full');
        let loadedCount = 0;
        const totalImages = images.length;
        
        if (totalImages === 0) {{
            adjustBubbleWidth();
            return;
        }}
        
        images.forEach(img => {{
            if (img.complete) {{
                loadedCount++;
                if (loadedCount === totalImages) {{
                    adjustBubbleWidth();
                }}
            }} else {{
                img.onload = () => {{
                    loadedCount++;
                    if (loadedCount === totalImages) {{
                        adjustBubbleWidth();
                    }}
                }};
                img.onerror = () => {{
                    loadedCount++;
                    if (loadedCount === totalImages) {{
                        adjustBubbleWidth();
                    }}
                }};
            }}
        }});
        
        setTimeout(() => {{
            adjustBubbleWidth();
        }}, 3000);
    }}
    
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', waitForImagesAndAdjust);
    }} else {{
        waitForImagesAndAdjust();
    }}
    </script>
</body>
</html>
        """

    def _build_html(self, messages: List[dict], show_title: bool = True, show_time: bool = True, show_date: bool = True) -> str:
        """构建 HTML 内容 - QQ 聊天气泡样式"""
        # 构建消息 HTML
        messages_html = ""
        for msg in messages:
            # 检查是否为日期分隔符
            if msg.get('type') == 'date_separator':
                if show_date:
                    date_str = self._escape_html(msg.get('date_str', ''))
                    messages_html += f'<div class="date-separator"><span class="date-text">{date_str}</span></div>\n'
                continue
            
            nickname = self._escape_html(msg.get('nickname', '未知用户'))
            card = msg.get('card', '')
            title = msg.get('title', '')  # 群头衔
            role = msg.get('role', 'member')  # 角色 (owner/admin/member)
            content = self._escape_html(msg.get('content', ''))
            time_str = self._escape_html(msg.get('time_str', ''))
            avatar_url = msg.get('avatar_url', '')
            reply_info = msg.get('reply_info')  # 回复信息

            # 头像 HTML
            if avatar_url:
                avatar_html = f'<img class="avatar" src="{avatar_url}" onerror="this.style.display=\'none\'">'
            else:
                avatar_html = f'<div class="avatar-placeholder">{nickname[0] if nickname else "?"}</div>'

            # 头部信息：群头衔 > 姓名 > 时间
            header_html = ""
            
            # 根据 role 和 title 决定头衔显示
            if show_title:
                if role == "owner":
                    header_html += '<span class="title-owner">群主</span>'
                elif role == "admin":
                    display_title = title if title else "管理员"
                    header_html += f'<span class="title-admin">{display_title}</span>'
                elif title:
                    header_html += f'<span class="title-special">{title}</span>'
            
            header_html += f'<span class="nickname">{card if card else nickname}</span>'
            if show_time and time_str:
                header_html += f'<span class="time">{time_str}</span>'

            # 回复预览 HTML
            reply_html = ""
            if reply_info:
                reply_nickname = self._escape_html(reply_info.get('nickname', ''))
                reply_content = reply_info.get('content', '')
                reply_content_html, _ = self._parse_content(reply_content)
                reply_html = f'''
                <div class="reply-preview">
                    <div class="reply-header">
                        <span class="reply-arrow">↩</span>
                        <span class="reply-nickname">{reply_nickname}</span>
                    </div>
                    <div class="reply-content">{reply_content_html}</div>
                </div>'''

            # 检查是否只有一张图片（没有回复预览时才生效）
            is_image_only, image_url = self._is_image_only(content)
            bubble_class = "bubble"
            content_html = ""
            
            if is_image_only and not reply_html:
                bubble_class = "bubble image-only"
                content_html = f'<img class="msg-image-full" src="{image_url}" alt="[图片]" onerror="this.outerHTML=\'[图片]\'">'
            else:
                content_html_parsed, _ = self._parse_content(content)
                content_html = f'<div class="message-content">{content_html_parsed}</div>'

            # 消息气泡
            messages_html += f"""
            <div class="message left">
                <div class="avatar-wrapper">
                    {avatar_html}
                </div>
                <div class="content-wrapper">
                    <div class="message-header">{header_html}</div>
                    <div class="{bubble_class}">
                        {reply_html}{content_html}
                    </div>
                </div>
            </div>
            """

        # 完整 HTML
        local_font_css = self._get_font_base64()
        
        font_cdn_links = ""
        if not local_font_css:
            font_cdn_links = """
    <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
    <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Regular/Regular.css" rel="stylesheet" media="print" onload="this.media='all'">
    <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Medium/Medium.css" rel="stylesheet" media="print" onload="this.media='all'">
    <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Bold/Bold.css" rel="stylesheet" media="print" onload="this.media='all'">
    <noscript>
        <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Regular/Regular.css" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Medium/Medium.css" rel="stylesheet">
        <link href="https://cdn.jsdelivr.net/npm/harmonyos-sans-webfont-splitted@latest/dist/HarmonyOS_Sans_SC/Bold/Bold.css" rel="stylesheet">
    </noscript>"""
        
        return self._build_html_template(messages_html, local_font_css, font_cdn_links)

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

    def _parse_content(self, content: str) -> tuple:
        """
        解析消息内容，支持 [图片](url) 格式

        Args:
            content: 原始消息内容

        Returns:
            (包含 HTML 标签的内容, 图片数量)
        """
        import re

        # 先提取图片标签和 URL，避免 URL 被转义
        image_pattern = r'\[图片\]\(([^)]+)\)'
        images = []
        
        def save_image(match):
            url = match.group(1)
            placeholder = f"__IMAGE_PLACEHOLDER_{len(images)}__"
            images.append(url)
            return placeholder
        
        # 临时替换图片标签
        content_temp = re.sub(image_pattern, save_image, content)
        
        # 转义 HTML 特殊字符
        escaped = self._escape_html(content_temp)
        
        # 恢复图片标签
        for i, url in enumerate(images):
            placeholder = f"__IMAGE_PLACEHOLDER_{i}__"
            img_tag = f'<img class="msg-image" src="{url}" alt="[图片]" onerror="this.outerHTML=\'[图片]\'">'
            escaped = escaped.replace(placeholder, img_tag)
        
        # 将换行符转换为 <br>
        result = escaped.replace('\n', '<br>')

        return result, len(images)

    def _is_image_only(self, content: str) -> tuple:
        """
        检查消息内容是否只有一张图片（没有其他文字内容）

        Args:
            content: 原始消息内容

        Returns:
            (是否只有一张图片, 图片URL)
        """
        import re
        
        image_pattern = r'\[图片\]\(([^)]+)\)'
        matches = list(re.finditer(image_pattern, content))
        
        if len(matches) != 1:
            return False, None
        
        # 检查除了图片标签外是否还有其他内容
        remaining = re.sub(image_pattern, '', content).strip()
        if remaining:
            return False, None
        
        return True, matches[0].group(1)
