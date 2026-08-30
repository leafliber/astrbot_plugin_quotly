"""
引用消息渲染器 - 使用 pytakumi 渲染 HTML
QQ 聊天气泡样式 1:1 复刻

pytakumi 是 Rust 布局引擎 Takumi 的 Python 绑定，纯 pip 安装，
无需浏览器和任何系统依赖。圆形头像通过 CSS border-radius: 50% +
object-fit: cover 由引擎原生裁剪，不再需要 html2pic 时代的
品红占位符 + 像素扫描 + Pillow 后处理方案。

卡片宽度采用两遍渲染：先 measure 出贴合内容的固有宽度
（受 .chat-container max-width 约束），再按该宽度出图，
复刻旧引擎 CONTENT_BOX 裁剪的"卡片贴合内容"效果。
"""

import asyncio
import base64
import hashlib
import io
import pathlib
import time
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Tuple
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
    "NotoColorEmoji.ttf": "https://cdn.jsdelivr.net/gh/googlefonts/noto-emoji/fonts/NotoColorEmoji.ttf",
}

FONT_WEIGHT_MAP = {
    "HarmonyOS_Sans_SC_Regular.ttf": 400,
    "HarmonyOS_Sans_SC_Medium.ttf": 500,
    "HarmonyOS_Sans_SC_Bold.ttf": 700,
}

AVATAR_MEMORY_CACHE_SIZE = 200
AVATAR_DISK_CACHE_TTL = 86400

AVATAR_SIZE = 80

# 卡片宽度约束，与 .chat-container 的 min/max-width 保持一致
RENDER_WIDTH_MIN = 200
RENDER_WIDTH_MAX = 1200

# CJK 场景建议在首次渲染前调大字形缓存（pytakumi 官方建议）
_GLYPH_CACHE_BYTES = 64 * 1024 * 1024


class LRUCache:
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
    _instance_count = 0
    _fonts_ready = False
    _font_lock = asyncio.Lock()
    _avatar_cache: Optional[LRUCache] = None

    # pytakumi Renderer 进程级单例，复用字形/图片解码缓存
    _engine = None
    _engine_lock = asyncio.Lock()
    # 原生渲染对象不做并发调用假设，串行化出图
    _render_lock = asyncio.Lock()

    def __init__(self):
        if HAS_ASTRBOT_PATH:
            data_path = get_astrbot_data_path()
            data_dir = (pathlib.Path(data_path) if isinstance(data_path, str)
                        else data_path) / "plugin_data" / "astrbot_plugin_quotly"
        else:
            data_dir = Path(__file__).parent.parent / "data"

        self._data_dir = data_dir
        self._fonts_dir = data_dir / "fonts"
        self._avatars_dir = data_dir / "avatars"
        self._fonts_dir.mkdir(parents=True, exist_ok=True)
        self._avatars_dir.mkdir(parents=True, exist_ok=True)

        if QuotlyRenderer._avatar_cache is None:
            QuotlyRenderer._avatar_cache = LRUCache(AVATAR_MEMORY_CACHE_SIZE)

        QuotlyRenderer._instance_count += 1
        logger.debug(f"QuotlyRenderer 实例创建，当前实例数: {QuotlyRenderer._instance_count}")

    async def ensure_fonts(self):
        if QuotlyRenderer._fonts_ready:
            return

        async with QuotlyRenderer._font_lock:
            if QuotlyRenderer._fonts_ready:
                return

            missing_fonts = []
            for font_file in FONT_DOWNLOAD_URLS:
                font_path = self._fonts_dir / font_file
                if not font_path.exists():
                    missing_fonts.append(font_file)

            if missing_fonts:
                logger.info(f"正在下载缺失的字体文件: {missing_fonts}")
                import aiohttp
                try:
                    async with aiohttp.ClientSession() as session:
                        download_tasks = [
                            self._download_font(session, font_file)
                            for font_file in missing_fonts
                        ]
                        await asyncio.gather(*download_tasks, return_exceptions=True)
                except Exception as e:
                    logger.error(
                        f"字体下载失败（无法连接 cdn.jsdelivr.net）: {e}\n"
                        "可手动下载字体文件放入 data/plugin_data/astrbot_plugin_quotly/fonts/ 目录，"
                        "详见 README「字体显示为方块 / 乱码」章节。"
                    )

            # 正文字体全部就绪即可，emoji 字体可选
            body_fonts_ready = all((self._fonts_dir / f).exists() for f in FONT_WEIGHT_MAP)
            if body_fonts_ready:
                QuotlyRenderer._fonts_ready = True
                emoji_ok = (self._fonts_dir / "NotoColorEmoji.ttf").exists()
                logger.info(f"字体加载完成（emoji 字体: {'已就绪' if emoji_ok else '未安装，emoji 可能无法显示'}）")
            else:
                logger.warning("部分字体文件缺失，将使用系统字体回退")

    async def _download_font(self, session, font_file: str) -> bool:
        url = FONT_DOWNLOAD_URLS[font_file]
        font_path = self._fonts_dir / font_file
        try:
            import aiohttp
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

    async def _ensure_engine(self):
        """创建 pytakumi Renderer 单例并注册字体，进程内只执行一次"""
        if QuotlyRenderer._engine is not None:
            return

        async with QuotlyRenderer._engine_lock:
            if QuotlyRenderer._engine is not None:
                return

            def _build_engine():
                import pytakumi
                pytakumi.set_glyph_cache_max_bytes(_GLYPH_CACHE_BYTES)
                engine = pytakumi.Renderer(cache_max_bytes=_GLYPH_CACHE_BYTES)

                registered = []
                for font_file, weight in FONT_WEIGHT_MAP.items():
                    font_path = self._fonts_dir / font_file
                    if font_path.exists():
                        try:
                            engine.register_font(
                                font_path.read_bytes(),
                                name="HarmonyOS Sans SC",
                                weight=weight,
                            )
                            registered.append(font_file)
                        except Exception as e:
                            logger.warning(f"字体注册失败: {font_file}, {e}")

                emoji_path = self._fonts_dir / "NotoColorEmoji.ttf"
                if emoji_path.exists():
                    try:
                        engine.register_font(emoji_path.read_bytes(), name="Noto Color Emoji")
                        registered.append("NotoColorEmoji.ttf")
                    except Exception as e:
                        # emoji 字体（CBDT 彩色格式）注册失败不影响正文渲染
                        logger.warning(f"emoji 字体注册失败（不影响正文渲染）: {e}")

                return engine, registered

            try:
                engine, registered = await asyncio.to_thread(_build_engine)
            except ImportError as e:
                raise ImportError(
                    f"pytakumi 导入失败: {e}\n"
                    "请确认已执行 pip install -r requirements.txt。"
                ) from e

            QuotlyRenderer._engine = engine
            logger.info(f"pytakumi 渲染引擎初始化完成，已注册字体: {registered}")

    async def cleanup(self):
        QuotlyRenderer._instance_count = max(0, QuotlyRenderer._instance_count - 1)
        logger.debug(f"QuotlyRenderer 实例清理，当前实例数: {QuotlyRenderer._instance_count}")

    async def arender(self, messages: List[dict], show_title: bool = True, show_time: bool = True,
                      show_date: bool = True, image_download_fallback=None) -> bytes:
        start_time = time.time()

        await self.ensure_fonts()
        await self._ensure_engine()

        self._image_download_fallback = image_download_fallback

        image_urls = set()
        for msg in messages:
            if msg.get('type') != 'date_separator':
                avatar_url = msg.get('avatar_url', '')
                if avatar_url and not avatar_url.startswith('data:'):
                    image_urls.add(avatar_url)
                content = msg.get('content', '')
                for url in self._extract_image_urls(content):
                    image_urls.add(url)

        if image_urls:
            preload_tasks = [self._preload_image(url) for url in image_urls]
            await asyncio.gather(*preload_tasks, return_exceptions=True)

        html, css, images_map = self._build_html_and_css(messages, show_title=show_title, show_time=show_time,
                                                         show_date=show_date)

        import pytakumi

        try:
            tree = pytakumi.from_html(html)
        except Exception as e:
            raise RuntimeError(f"pytakumi HTML 解析失败: {e}") from e

        def _do_render():
            # 两遍渲染：先测固有宽度（受 max-width 约束），再按该宽度出图
            measured = QuotlyRenderer._engine.measure(
                tree, width=None, stylesheets=[css],
                images=images_map if images_map else None,
            )
            content_width = int(measured.get("width") or RENDER_WIDTH_MAX)
            content_width = max(RENDER_WIDTH_MIN, min(content_width, RENDER_WIDTH_MAX))
            return QuotlyRenderer._engine.render(
                tree, width=content_width, stylesheets=[css],
                images=images_map if images_map else None,
            )

        async with QuotlyRenderer._render_lock:
            try:
                png_data = await asyncio.to_thread(_do_render)
            except Exception as e:
                raise RuntimeError(f"pytakumi 渲染失败: {e}") from e

        elapsed = time.time() - start_time
        logger.debug(f"渲染完成，耗时: {elapsed:.2f}秒")

        return png_data

    @staticmethod
    def _extract_image_urls(content: str) -> list:
        import re
        return re.findall(r'\[图片\]\(([^)]+)\)', content)

    def _avatar_cache_key(self, url: str) -> str:
        return hashlib.md5(url.encode()).hexdigest()

    async def _preload_image(self, url: str, prefix: str = ""):
        if not url or url.startswith('data:'):
            return

        # Local file path - no download needed
        if Path(url).is_file():
            return

        cache_key = prefix + self._avatar_cache_key(url)

        disk_path = self._avatars_dir / cache_key
        if disk_path.exists():
            try:
                mtime = disk_path.stat().st_mtime
                if time.time() - mtime < AVATAR_DISK_CACHE_TTL:
                    data = disk_path.read_bytes()
                    await QuotlyRenderer._avatar_cache.set(cache_key, data)
                    return
                else:
                    logger.debug(f"图片磁盘缓存已过期，将重新下载: {url[:50]}...")
            except Exception as e:
                logger.debug(f"读取磁盘缓存失败: {e}")

        cached = await QuotlyRenderer._avatar_cache.get(cache_key)
        if cached is not None:
            return

        # 方案 1: HTTP 直接下载
        downloaded = False
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        await QuotlyRenderer._avatar_cache.set(cache_key, data)
                        try:
                            disk_path.write_bytes(data)
                        except Exception as e:
                            logger.debug(f"写入磁盘缓存失败: {e}")
                        logger.debug(f"预加载图片(HTTP): {url[:50]}...")
                        downloaded = True
        except Exception as e:
            logger.debug(f"HTTP 下载失败: {url[:80]}..., 错误: {e}")

        # 方案 2: 使用备用下载回调（如 OneBot download_file API）
        if not downloaded:
            fallback = getattr(self, '_image_download_fallback', None)
            if fallback:
                try:
                    local_path = await fallback(url)
                    if local_path and Path(local_path).is_file():
                        data = Path(local_path).read_bytes()
                        await QuotlyRenderer._avatar_cache.set(cache_key, data)
                        try:
                            disk_path.write_bytes(data)
                        except Exception as e:
                            logger.debug(f"写入磁盘缓存失败: {e}")
                        logger.debug(f"预加载图片(备用): {url[:50]}...")
                        downloaded = True
                        # 已缓存到本地，清理 OneBot 下载的原始文件
                        try:
                            Path(local_path).unlink()
                        except OSError:
                            pass
                except Exception as e:
                    logger.debug(f"备用下载失败: {url[:80]}..., 错误: {e}")

        if not downloaded:
            logger.warning(f"图片预加载全部失败: {url[:80]}...")

    def _get_image_bytes(self, url: str) -> Optional[bytes]:
        """解析消息中的图片引用为字节：data URL / 本地路径 / 磁盘缓存"""
        if not url:
            return None

        if url.startswith('data:'):
            return self._decode_data_url(url)

        if Path(url).is_file():
            try:
                return Path(url).read_bytes()
            except Exception as e:
                logger.debug(f"读取本地图片失败: {url}, {e}")
                return None

        cache_key = self._avatar_cache_key(url)
        disk_path = self._avatars_dir / cache_key
        if disk_path.exists():
            try:
                return disk_path.read_bytes()
            except Exception:
                return None

        return None

    @staticmethod
    def _decode_data_url(url: str) -> Optional[bytes]:
        """解码 data:image/...;base64,... 形式的内嵌图片"""
        try:
            header, _, payload = url.partition(',')
            if 'base64' in header.lower() and payload:
                return base64.b64decode(payload)
        except Exception:
            pass
        return None

    def _build_html_and_css(self, messages: List[dict], show_title: bool = True,
                            show_time: bool = True, show_date: bool = True) -> Tuple[str, str, dict]:
        self._reset_image_sizing()
        messages_html = ""
        is_first_date = True
        images_map = {}

        for msg in messages:
            if msg.get('type') == 'date_separator':
                if show_date:
                    date_str = self._escape_html(msg.get('date_str', ''))
                    first_class = ' first-date' if is_first_date else ''
                    messages_html += f'<div class="date-separator{first_class}"><span class="date-text">{date_str}</span></div>\n'
                    is_first_date = False
                continue

            is_first_date = False
            nickname = self._escape_html(msg.get('nickname', '未知用户'))
            card = msg.get('card', '')
            title = msg.get('title', '')
            role = msg.get('role', 'member')
            content = msg.get('content', '')
            time_str = self._escape_html(msg.get('time_str', ''))
            avatar_url = msg.get('avatar_url', '')
            reply_info = msg.get('reply_info')

            avatar_html = ""
            if avatar_url:
                avatar_bytes = self._get_image_bytes(avatar_url)
                if avatar_bytes:
                    mem_key = f"mem://avatar-{len(images_map)}"
                    images_map[mem_key] = avatar_bytes
                    # 圆形裁剪由引擎原生完成
                    avatar_html = f'<img class="avatar" src="{mem_key}">'

            if not avatar_html:
                initial = nickname[0] if nickname else "?"
                avatar_html = (
                    f'<div class="avatar avatar-placeholder">'
                    f'<span class="avatar-initial">{initial}</span></div>'
                )

            header_html = ""

            if show_title:
                if role == "owner":
                    header_html += '<span class="title-owner">群主</span>'
                elif role == "admin":
                    display_title = title if title else "管理员"
                    header_html += f'<span class="title-admin">{self._escape_html(display_title)}</span>'
                elif title:
                    header_html += f'<span class="title-special">{self._escape_html(title)}</span>'

            header_html += f'<span class="nickname">{card if card else nickname}</span>'
            if show_time and time_str:
                header_html += f'<span class="time">{time_str}</span>'

            reply_html = ""
            if reply_info:
                reply_nickname = self._escape_html(reply_info.get('nickname', ''))
                reply_content = reply_info.get('content', '')
                reply_content_html = self._parse_content(reply_content, images_map, 150, 80)
                reply_html = f'''
                <div class="reply-preview">
                    <div class="reply-header">
                        <span class="reply-nickname">{reply_nickname}</span>
                    </div>
                    <div class="reply-content">{reply_content_html}</div>
                </div>'''

            is_image_only, image_url = self._is_image_only(content)
            bubble_class = "bubble"
            content_html = ""

            if is_image_only and not reply_html:
                bubble_class = "bubble image-only"
                image_bytes = self._get_image_bytes(image_url)
                if image_bytes:
                    mem_key = f"mem://image-{len(images_map)}"
                    images_map[mem_key] = image_bytes
                    size_class = self._image_size_class(image_url, 600, 800)
                    img_class = "msg-image-full" + (f" {size_class}" if size_class else "")
                    content_html = f'<img class="{img_class}" src="{mem_key}">'
                else:
                    content_html = '<div class="image-fallback">[图片]</div>'
            else:
                content_html_parsed = self._parse_content(content, images_map)
                content_html = f'<div class="message-content">{content_html_parsed}</div>'

            messages_html += f"""
            <div class="message">
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

        css = self._build_css()
        if self._image_size_rules:
            css += "\n" + "\n".join(self._image_size_rules.values())
        html = f'<div class="chat-container">{messages_html}</div>'

        return html, css, images_map

    def _reset_image_sizing(self):
        """每次渲染前重置图片尺寸规则收集器"""
        self._image_size_rules = {}
        self._image_size_counter = 0

    def _image_size_class(self, url: str, max_w: int, max_h: int) -> str:
        """
        为图片计算等比缩放后的精确 width/height，返回唯一 CSS class 名。

        显式给每张图精确尺寸，让布局盒与图片宽高比一致，避免引擎按
        固有尺寸测量导致宽图被裁或比例失真。

        读不到图片尺寸时返回空串（调用方回退到 max-width 约束）。
        """
        data = self._get_image_bytes(url)
        if not data:
            return ""
        try:
            from PIL import Image as PILImage
            with PILImage.open(io.BytesIO(data)) as im:
                iw, ih = im.size
        except Exception:
            return ""
        if iw <= 0 or ih <= 0:
            return ""

        scale = min(max_w / iw, max_h / ih, 1.0)
        dw = max(1, round(iw * scale))
        dh = max(1, round(ih * scale))
        self._image_size_counter += 1
        cls = f"qimg-{self._image_size_counter}"
        # 同时解除 .msg-image 的 min-width/min-height 约束，确保精确尺寸完全生效
        self._image_size_rules[cls] = (
            f".{cls} {{ width: {dw}px; height: {dh}px; min-width: 0; min-height: 0; }}"
        )
        return cls

    def _build_css(self) -> str:
        return f"""
        * {{
            margin: 0;
            padding: 0;
            font-family: 'HarmonyOS Sans SC', 'Noto Color Emoji', -apple-system, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
        }}

        .chat-container {{
            background-color: #ebebf0;
            padding: 30px;
            min-width: 200px;
            max-width: 1200px;
        }}

        .date-separator {{
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 40px 0 20px 0;
            width: 100%;
        }}

        .date-separator.first-date {{
            margin-top: 0;
        }}

        .date-text {{
            color: #999;
            font-size: 26px;
        }}

        .message {{
            display: flex;
            margin: 32px 0;
            align-items: start;
        }}

        .avatar-wrapper {{
            flex-shrink: 0;
        }}

        .avatar {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            object-fit: cover;
            display: block;
        }}

        .avatar-placeholder {{
            background-image: linear-gradient(135deg, #667eea, #764ba2);
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .avatar-initial {{
            color: #ffffff;
            font-size: 30px;
            font-weight: 500;
        }}

        .content-wrapper {{
            margin-left: 24px;
            flex-grow: 0;
            flex-shrink: 1;
            display: flex;
            flex-direction: column;
            align-items: flex-start;
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
            background-color: #fff9e6;
            padding: 4px 16px;
            border-radius: 8px;
            font-size: 24px;
        }}

        .title-admin {{
            color: #1a9f06;
            background-color: #e6f7e6;
            padding: 4px 16px;
            border-radius: 8px;
            font-size: 24px;
        }}

        .title-special {{
            color: #7b1fa2;
            background-color: #f3e5f5;
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
            background-color: #ffffff;
            border-radius: 24px;
            padding: 16px 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
            min-width: 100px;
            max-width: 1100px;
        }}

        .message-content {{
            font-size: 32px;
            line-height: 1.6;
            color: #1a1a1a;
        }}

        .msg-image {{
            max-width: 600px;
            min-width: 150px;
            max-height: 800px;
            border-radius: 8px;
            margin-top: 8px;
            display: block;
        }}

        .bubble.image-only {{
            padding: 0;
            overflow: hidden;
        }}

        .msg-image-full {{
            max-width: 600px;
            max-height: 800px;
            border-radius: 24px;
            display: block;
        }}

        .image-fallback {{
            padding: 16px 20px;
            color: #999;
            font-size: 32px;
            line-height: 1.4;
        }}

        .image-fallback-inline {{
            color: #999;
            font-size: 28px;
        }}

        .reply-preview {{
            background-color: #f5f5f5;
            padding: 8px 12px;
            margin-bottom: 10px;
            border-radius: 4px;
            font-size: 26px;
            color: #666;
            max-width: 100%;
        }}

        .reply-header {{
            display: flex;
            align-items: center;
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
            border-radius: 4px;
        }}"""

    # Unicode 双向控制字符及其他不可见格式字符，会导致文本整形渲染异常
    _BIDI_CONTROL_CHARS = str.maketrans('', '', ''.join(chr(c) for c in (
        *range(0x200B, 0x2010),  # ZWSP, ZWNJ, ZWJ, LRM, RLM, NNBSP, ZWNBSP
        *range(0x2028, 0x202F),  # LRE, RLE, PDF, LRO, RLO, NARS, ASS, ISS, AFS
        *range(0x2066, 0x2070),  # LRI, RLI, FSI, PDI
        0xFEFF,                   # BOM / ZWNBSP
        0x034F,                   # CGJ (Combining Grapheme Joiner)
    )))

    def _escape_html(self, text: str) -> str:
        if not text:
            return ""
        text = text.translate(self._BIDI_CONTROL_CHARS)
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

    def _parse_content(self, content: str, images_map: dict, max_w: int = 600, max_h: int = 800) -> str:
        import re

        image_pattern = r'\[图片\]\(([^)]+)\)'
        parts = []
        last_end = 0

        for match in re.finditer(image_pattern, content):
            if match.start() > last_end:
                text_part = content[last_end:match.start()]
                parts.append(self._text_to_html(text_part))

            image_url = match.group(1)
            image_bytes = self._get_image_bytes(image_url)
            if image_bytes:
                mem_key = f"mem://image-{len(images_map)}"
                images_map[mem_key] = image_bytes
                size_class = self._image_size_class(image_url, max_w, max_h)
                img_class = "msg-image" + (f" {size_class}" if size_class else "")
                parts.append(f'<img class="{img_class}" src="{mem_key}">')
            else:
                parts.append('<span class="image-fallback-inline">[图片]</span>')
            last_end = match.end()

        if last_end < len(content):
            parts.append(self._text_to_html(content[last_end:]))

        return "".join(parts) if parts else self._text_to_html(content)

    def _text_to_html(self, text: str) -> str:
        escaped = self._escape_html(text)
        return escaped.replace("\n", "<br>")

    def _is_image_only(self, content: str) -> tuple:
        import re

        image_pattern = r'\[图片\]\(([^)]+)\)'
        matches = list(re.finditer(image_pattern, content))

        if len(matches) != 1:
            return False, None

        remaining = re.sub(image_pattern, '', content).strip()
        if remaining:
            return False, None

        return True, matches[0].group(1)
