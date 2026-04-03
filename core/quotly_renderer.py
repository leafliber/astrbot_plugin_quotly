"""
SVG 渲染器 - 核心渲染模块
使用纯 Python 方案：HTML 模板 + Pillow 绘制
"""

import base64
from io import BytesIO
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont


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

        # 加载字体
        self.font_regular = ImageFont.truetype(str(font_path), 28)
        self.font_bold = ImageFont.truetype(str(font_path), 28)
        self.font_small = ImageFont.truetype(str(font_path), 24)

        # 读取字体文件（base64 备用）
        with open(font_path, 'rb') as f:
            self.font_base64 = base64.b64encode(f.read()).decode('ascii')

        # 渲染参数
        self.avatar_size = 80
        self.bubble_padding = 20
        self.message_spacing = 30
        self.line_height = 32
        self.width = 800

    def render(self, messages: List[dict]) -> bytes:
        """
        渲染消息列表为 PNG 图片

        Args:
            messages: 消息列表，每条消息包含:
                - nickname: 发送者昵称
                - card: 群名片（可选）
                - user_id: QQ 号
                - content: 消息内容
                - time_str: 格式化的时间字符串
                - avatar_url: 头像 URL（可选）

        Returns:
            PNG 格式的字节数据
        """
        # 计算图片高度
        total_height = self._calculate_height(messages)

        # 创建图片
        img = Image.new('RGB', (self.width, total_height), '#ffffff')
        draw = ImageDraw.Draw(img)

        # 绘制每条消息
        y_offset = 20
        for msg in messages:
            msg_height = self._render_message(draw, img, msg, y_offset)
            y_offset += msg_height + self.message_spacing

        # 保存到字节流
        output = BytesIO()
        img.save(output, format='PNG')
        return output.getvalue()

    def _calculate_height(self, messages: List[dict]) -> int:
        """计算图片总高度"""
        height = 40  # padding
        for msg in messages:
            content = msg.get('content', '')
            content_lines = self._wrap_text(content)
            # 头像高度 + 内容行数 * 行高 + padding
            msg_height = self.avatar_size + len(content_lines) * self.line_height + 60
            height += max(self.avatar_size + 40, msg_height)
        return max(height, 200)

    def _render_message(self, draw: ImageDraw.Draw, img: Image, msg: dict, y_offset: float) -> float:
        """
        渲染单条消息

        Args:
            draw: ImageDraw 对象
            img: Image 对象
            msg: 消息数据
            y_offset: Y 轴偏移

        Returns:
            渲染的该消息占用的高度
        """
        nickname = msg.get('nickname', '未知用户')
        card = msg.get('card', '')
        display_name = card if card else nickname
        content = msg.get('content', '')
        time_str = msg.get('time_str', '')

        # 布局参数
        avatar_x = 30
        avatar_y = y_offset + 10
        text_x = avatar_x + self.avatar_size + 25
        text_max_width = self.width - text_x - 30

        # 文字换行
        content_lines = self._wrap_text(content, text_max_width)

        # 计算高度
        content_height = len(content_lines) * self.line_height
        bubble_height = max(self.avatar_size + 20, content_height + 70)

        # 绘制气泡背景
        bubble_y = avatar_y - 10
        draw.rounded_rectangle(
            [avatar_x - 15, bubble_y, self.width - 20, bubble_y + bubble_height],
            radius=15,
            fill='#f5f5f5'
        )

        # 绘制圆形头像背景
        avatar_center_x = avatar_x + self.avatar_size // 2
        avatar_center_y = avatar_y + self.avatar_size // 2
        draw.ellipse(
            [avatar_x, avatar_y, avatar_x + self.avatar_size, avatar_y + self.avatar_size],
            fill='#e8e8e8'
        )

        # 绘制默认头像文字（如果没头像）
        avatar_url = msg.get('avatar_url')
        if not avatar_url:
            # 绘制昵称首字
            initial = nickname[0] if nickname else '?'
            # 计算文字居中位置
            bbox = draw.textbbox((0, 0), initial, font=self.font_bold)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            draw.text(
                (avatar_center_x - text_w // 2, avatar_center_y - text_h // 2 - 5),
                initial,
                fill='#888888',
                font=self.font_bold
            )

        # 绘制昵称
        draw.text((text_x, avatar_y), display_name, fill='#1f1f1f', font=self.font_bold)

        # 绘制时间
        if time_str:
            time_bbox = draw.textbbox((0, 0), time_str, font=self.font_small)
            time_w = time_bbox[2] - time_bbox[0]
            draw.text((text_x + time_w + 20, avatar_y + 3), time_str, fill='#888888', font=self.font_small)

        # 绘制消息内容
        content_y = avatar_y + 45
        for line in content_lines:
            draw.text((text_x, content_y), line, fill='#1f1f1f', font=self.font_regular)
            content_y += self.line_height

        return bubble_height

    def _wrap_text(self, text: str, max_width: Optional[int] = None) -> List[str]:
        """
        文字换行

        Args:
            text: 原始文本
            max_width: 最大宽度（像素）

        Returns:
            换行后的文本列表
        """
        if max_width is None:
            max_width = self.width - 200

        if not text:
            return [""]

        lines = []
        current_line = ""

        for char in text:
            test_line = current_line + char
            bbox = self.font_regular.getbbox(test_line)
            test_width = bbox[2] - bbox[0]

            if test_width > max_width:
                if current_line:
                    lines.append(current_line)
                current_line = char
            else:
                current_line = test_line

        if current_line:
            lines.append(current_line)

        return lines if lines else [""]


def html_to_png(html_content: str, font_path: str, width: int = 800) -> bytes:
    """
    HTML 转 PNG 的辅助函数（备用方案）
    使用 Pillow 直接绘制简化 HTML 内容

    Args:
        html_content: HTML 内容
        font_path: 字体文件路径
        width: 图片宽度

    Returns:
        PNG 格式字节数据
    """
    from selectolax.parser import HTMLParser

    parser = HTMLParser(html_content)

    # 创建图片
    img = Image.new('RGB', (width, 200), '#ffffff')
    draw = ImageDraw.Draw(img)

    # 加载字体
    font = ImageFont.truetype(font_path, 24)

    # 提取文本并绘制（简化处理）
    text_content = []
    for node in parser.tags('p'):
        if node.text():
            text_content.append(node.text())

    y = 20
    for text in text_content:
        draw.text((20, y), text.strip(), fill='#1f1f1f', font=font)
        y += 30

    output = BytesIO()
    img.save(output, format='PNG')
    return output.getvalue()
