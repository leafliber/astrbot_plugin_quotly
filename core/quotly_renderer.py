"""
引用消息渲染器 - 使用 html2pic 渲染 HTML
QQ 聊天气泡样式 1:1 复刻

html2pic 基于 Skia + Taffy + HarfBuzz，纯 pip 安装，无需浏览器。

注意：html2pic 在 flex 布局中 border-radius 无法正确裁剪背景，
因此头像采用 Pillow 后处理方案——先用 html2pic 渲染整体布局，
再用 Pillow 将方形头像区域替换为圆形头像。
"""

import asyncio
import hashlib
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
}

FONT_WEIGHT_MAP = {
    "HarmonyOS_Sans_SC_Regular.ttf": 400,
    "HarmonyOS_Sans_SC_Medium.ttf": 500,
    "HarmonyOS_Sans_SC_Bold.ttf": 700,
}

AVATAR_MEMORY_CACHE_SIZE = 200
AVATAR_DISK_CACHE_TTL = 86400

# html2pic 在 flex 布局中 border-radius 无法裁剪背景，头像用 Pillow 后处理
# 此颜色用作头像占位标记，渲染后扫描替换为圆形头像
_AVATAR_MARKER_RGB = (255, 0, 255)  # 品红 #FF00FF
AVATAR_SIZE = 80


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

            all_exist = all((self._fonts_dir / f).exists() for f in FONT_DOWNLOAD_URLS)
            if all_exist:
                QuotlyRenderer._fonts_ready = True
                logger.info("字体加载完成")
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

    def _build_font_css(self) -> str:
        font_faces = []
        for font_file, weight in FONT_WEIGHT_MAP.items():
            font_path = self._fonts_dir / font_file
            if font_path.exists():
                font_faces.append(
                    f"@font-face {{ font-family: 'HarmonyOS Sans SC'; "
                    f"src: url('{font_path}') format('truetype'); "
                    f"font-weight: {weight}; font-style: normal; }}"
                )

        return "\n".join(font_faces) if font_faces else ""

    async def cleanup(self):
        QuotlyRenderer._instance_count = max(0, QuotlyRenderer._instance_count - 1)
        logger.debug(f"QuotlyRenderer 实例清理，当前实例数: {QuotlyRenderer._instance_count}")

    async def arender(self, messages: List[dict], show_title: bool = True, show_time: bool = True,
                      show_date: bool = True) -> bytes:
        start_time = time.time()

        await self.ensure_fonts()

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

        html, css, avatar_data_list = self._build_html_and_css(messages, show_title=show_title, show_time=show_time,
                                              show_date=show_date)

        try:
            from html2pic import Html2Pic
            from pictex import CropMode
        except ImportError as e:
            raise ImportError(
                f"html2pic 导入失败: {e}\n"
                "请确认已执行 pip install -r requirements.txt。\n"
                "Linux 用户可能需要先安装系统依赖，详见 README「系统依赖」章节。"
            ) from e

        try:
            renderer = Html2Pic(html, css)
            image = renderer.render(crop_mode=CropMode.CONTENT_BOX)
        except Exception as e:
            raise RuntimeError(
                f"html2pic 渲染失败: {e}\n"
                "Linux/Docker 用户请确认已安装 fontconfig 和 OpenGL 系统库，详见 README「系统依赖」章节。"
            ) from e

        import io
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        try:
            pil_image = image.to_pillow().convert("RGBA")
        except Exception as e:
            raise RuntimeError(
                f"图像转换失败: {e}\n"
                "请确认 Pillow 和 numpy 已正确安装（pip install Pillow numpy）。"
            ) from e

        # 后处理：将方形头像标记替换为圆形头像
        if avatar_data_list:
            from PIL import Image as PILImage
            arr = np.array(pil_image)
            marker_rgb = np.array(_AVATAR_MARKER_RGB, dtype=np.uint8)
            marker_positions = self._find_avatar_markers(arr, marker_rgb)

            for idx, (ax, ay) in enumerate(marker_positions):
                if idx >= len(avatar_data_list):
                    break
                avatar_info = avatar_data_list[idx]
                avatar_img = self._create_avatar_image(avatar_info)
                if avatar_img:
                    # 先用背景色填充标记区域（清除标记色），再粘贴圆形头像
                    bg_box = PILImage.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), (235, 235, 240, 255))
                    pil_image.paste(bg_box, (ax, ay))
                    pil_image.paste(avatar_img, (ax, ay), avatar_img)

        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")

        elapsed = time.time() - start_time
        logger.debug(f"渲染完成，耗时: {elapsed:.2f}秒")

        return buf.getvalue()

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
                        logger.debug(f"预加载图片: {url[:50]}...")
        except Exception as e:
            logger.debug(f"预加载图片失败: {url[:50]}..., 错误: {e}")

    def _get_avatar_src(self, url: str) -> str:
        if not url:
            return ""

        if url.startswith('data:'):
            return url

        cache_key = self._avatar_cache_key(url)
        disk_path = self._avatars_dir / cache_key
        if disk_path.exists():
            try:
                mtime = disk_path.stat().st_mtime
                if time.time() - mtime < AVATAR_DISK_CACHE_TTL:
                    return str(disk_path)
            except Exception:
                pass

        return ""

    def _build_html_and_css(self, messages: List[dict], show_title: bool = True,
                            show_time: bool = True, show_date: bool = True) -> Tuple[str, str, list]:
        font_css = self._build_font_css()
        messages_html = ""
        is_first_date = True
        avatar_data_list = []

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
                avatar_src = self._get_avatar_src(avatar_url)
                if avatar_src:
                    # 用标记色方块占位，渲染后 Pillow 替换为圆形头像
                    avatar_html = '<div class="avatar-marker"></div>'
                    # 记录头像数据用于后处理
                    avatar_data_list.append({"type": "image", "src": avatar_src})

            if not avatar_html:
                initial = nickname[0] if nickname else "?"
                # 用标记色方块占位
                avatar_html = '<div class="avatar-marker"></div>'
                avatar_data_list.append({
                    "type": "placeholder",
                    "initial": initial,
                })

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
                reply_content_html, _ = self._parse_content(reply_content)
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
                image_src = self._get_local_image_path(image_url)
                if image_src:
                    content_html = f'<div class="msg-image-full" style="background-image: url(\'{image_src}\');"></div>'
                else:
                    content_html = '<span>[图片]</span>'
            else:
                content_html_parsed, _ = self._parse_content(content)
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

        css = self._build_css(font_css)
        html = f'<div class="chat-container">{messages_html}</div>'

        return html, css, avatar_data_list

    def _get_local_image_path(self, url: str) -> str:
        if not url:
            return ""

        # Local file path - use directly
        if Path(url).is_file():
            return url

        # data: URL - save to file for html2pic compatibility
        if url.startswith('data:'):
            try:
                import base64
                import re
                match = re.match(r'data:([^;]+);base64,(.+)', url, re.DOTALL)
                if match:
                    mime = match.group(1)
                    b64_data = match.group(2)
                    ext = {
                        'image/png': '.png',
                        'image/jpeg': '.jpg',
                        'image/gif': '.gif',
                        'image/webp': '.webp',
                    }.get(mime, '.png')

                    cache_key = self._avatar_cache_key(url)
                    disk_path = self._avatars_dir / f"{cache_key}{ext}"

                    if not disk_path.exists():
                        img_data = base64.b64decode(b64_data)
                        disk_path.write_bytes(img_data)

                    return str(disk_path)
            except Exception as e:
                logger.debug(f"保存 data URL 图片失败: {e}")
            return ""

        cache_key = self._avatar_cache_key(url)
        disk_path = self._avatars_dir / cache_key
        if disk_path.exists():
            return str(disk_path)

        return ""

    @staticmethod
    def _find_avatar_markers(arr: "np.ndarray", marker_rgb: "np.ndarray") -> List[Tuple[int, int]]:
        """扫描渲染结果，找到所有头像标记色的中心坐标，返回头像区域左上角 (x, y)"""
        import numpy as np
        h, w = arr.shape[:2]

        # 快速：只扫描标记色存在的行
        row_matches = np.any(
            np.all(np.abs(arr[:, :, :3].astype(int) - marker_rgb.astype(int)) < 20, axis=2),
            axis=1
        )
        match_rows = np.where(row_matches)[0]
        if len(match_rows) == 0:
            return []

        # 按连续行分组，每组是一个头像（或头像的一部分）
        groups = []
        start = match_rows[0]
        prev = match_rows[0]
        for r in match_rows[1:]:
            if r > prev + 5:
                groups.append((start, prev))
                start = r
            prev = r
        groups.append((start, prev))

        # 合并相邻的组（同一个头像可能被 html2pic 渲染成多段）
        # 阈值用 AVATAR_SIZE//2 而非 AVATAR_SIZE：短消息时相邻头像间隙约 73px，
        # 若用 80 会把两条消息的头像错误合并为一组，导致第二个头像不被替换。
        merge_gap = AVATAR_SIZE // 2
        merged = []
        i = 0
        while i < len(groups):
            sy, ey = groups[i]
            while i + 1 < len(groups) and groups[i + 1][0] - ey < merge_gap:
                i += 1
                ey = groups[i][1]
            merged.append((sy, ey))
            i += 1

        # 找到每个合并组的 x 范围，计算居中位置
        positions = []
        for sy, ey in merged:
            # 在此 y 范围内找到标记色的 x 范围
            region = arr[sy:ey + 1, :, :3]
            col_matches = np.any(
                np.all(np.abs(region.astype(int) - marker_rgb.astype(int)) < 20, axis=2),
                axis=0
            )
            match_cols = np.where(col_matches)[0]
            if len(match_cols) == 0:
                continue
            cx = match_cols[0]
            cy = sy
            positions.append((int(cx), int(cy)))

        return positions

    def _create_avatar_image(self, avatar_info: dict):
        """创建圆形头像 RGBA 图像（带抗锯齿边缘）"""
        from PIL import Image, ImageDraw, ImageFont

        size = AVATAR_SIZE
        # 4x 超采样抗锯齿：在大画布上绘制，缩回原尺寸
        supersample = 4
        big_size = size * supersample

        avatar_type = avatar_info.get("type")

        if avatar_type == "image":
            src = avatar_info.get("src", "")
            try:
                img = Image.open(src).convert("RGBA")
                img = img.resize((big_size, big_size), Image.LANCZOS)
            except Exception:
                logger.debug(f"打开头像图片失败: {src}")
                img = self._create_gradient_avatar(avatar_info.get("initial", "?"), big_size)
        else:
            initial = avatar_info.get("initial", "?")
            img = self._create_gradient_avatar(initial, big_size)

        # 创建高分辨率圆形 mask
        mask = Image.new("L", (big_size, big_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, big_size - 1, big_size - 1], fill=255)

        # 应用 mask
        output = Image.new("RGBA", (big_size, big_size), (0, 0, 0, 0))
        output.paste(img, (0, 0), mask)

        # 缩回原尺寸，LANCZOS 插值产生抗锯齿边缘
        output = output.resize((size, size), Image.LANCZOS)
        return output

    def _load_font(self, size: int):
        """加载字体：优先已下载的 HarmonyOS Sans SC，回退系统 CJK 字体"""
        from PIL import ImageFont

        # 优先使用已下载的 HarmonyOS Sans SC Medium（适中粗细适合头像首字）
        if hasattr(self, '_fonts_dir'):
            medium_path = self._fonts_dir / "HarmonyOS_Sans_SC_Medium.ttf"
            if medium_path.exists():
                try:
                    return ImageFont.truetype(str(medium_path), size)
                except Exception:
                    pass

        # 回退系统 CJK 字体
        font_candidates = [
            # Windows
            "msyh.ttc",       # 微软雅黑
            "msyhbd.ttc",     # 微软雅黑粗体
            "simhei.ttf",     # 黑体
            # macOS
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            # Linux
            "NotoSansCJK-Regular.ttc",
            "WenQuanYiMicroHei.ttf",
            "DroidSansFallbackFull.ttf",
        ]
        for name in font_candidates:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _create_gradient_avatar(self, initial: str, size: int):
        """创建渐变色头像（带首字），size 可以是超采样尺寸"""
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 绘制渐变背景（简化：用纯色模拟，避免 Pillow gradient 复杂度）
        # 从 #667eea 到 #764ba2 的渐变
        for y in range(size):
            ratio = y / max(size - 1, 1)
            r = int(102 + (118 - 102) * ratio)
            g = int(126 + (75 - 126) * ratio)
            b = int(234 + (162 - 234) * ratio)
            draw.line([(0, y), (size - 1, y)], fill=(r, g, b, 255))

        # 绘制首字（字号按 size 缩放）
        font_size = max(int(size * 0.35), 12)
        font = self._load_font(font_size)

        bbox = draw.textbbox((0, 0), initial, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (size - tw) // 2
        ty = (size - th) // 2 - bbox[1]
        draw.text((tx, ty), initial, fill=(255, 255, 255, 255), font=font)

        return img

    def _build_css(self, font_css: str) -> str:
        return f"""
        {font_css}

        * {{
            margin: 0;
            padding: 0;
            font-family: 'HarmonyOS Sans SC', -apple-system, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
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

        .avatar-marker {{
            width: 80px;
            height: 80px;
            background-color: #FF00FF;
        }}

        .content-wrapper {{
            margin-left: 24px;
            flex-grow: 0;
            flex-shrink: 1;
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
            min-width: 300px;
            max-height: 800px;
            border-radius: 8px;
            margin-top: 8px;
            background-size: contain;
            background-position: center;
            background-repeat: no-repeat;
        }}

        .bubble.image-only {{
            padding: 0;
            line-height: 0;
        }}

        .msg-image-full {{
            width: 600px;
            max-height: 800px;
            border-radius: 24px;
            background-size: cover;
            background-position: center;
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
        }}
        """

    def _escape_html(self, text: str) -> str:
        if not text:
            return ""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

    def _parse_content(self, content: str) -> tuple:
        import re

        image_pattern = r'\[图片\]\(([^)]+)\)'
        parts = []
        last_end = 0

        for match in re.finditer(image_pattern, content):
            if match.start() > last_end:
                text_part = content[last_end:match.start()]
                parts.append(self._text_to_html(text_part))

            image_url = match.group(1)
            image_src = self._get_local_image_path(image_url)
            if image_src:
                parts.append(f'<div class="msg-image" style="background-image: url(\'{image_src}\'); width: 300px; height: 200px;"></div>')
            else:
                parts.append('[图片]')
            last_end = match.end()

        if last_end < len(content):
            parts.append(self._text_to_html(content[last_end:]))

        return "".join(parts) if parts else self._text_to_html(content), None

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
