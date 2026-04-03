"""
SVG 渲染器单元测试
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.quotly_renderer import QuotlyRenderer


class TestQuotlyRenderer:
    """QuotlyRenderer 测试类"""

    def setup_method(self):
        """每个测试方法执行前的setup"""
        font_dir = Path(__file__).parent.parent / "assets" / "fonts"
        self.renderer = QuotlyRenderer(str(font_dir))

    def test_render_single_message(self):
        """测试渲染单条消息"""
        messages = [
            {
                "nickname": "测试用户",
                "card": "群名片",
                "user_id": 123456,
                "content": "这是一条测试消息",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = self.renderer.render(messages)

        # 验证返回的是 PNG 格式的字节数据
        assert isinstance(result, bytes)
        # PNG 文件头是固定的
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_multiple_messages(self):
        """测试渲染多条消息"""
        messages = [
            {
                "nickname": "用户A",
                "card": "",
                "user_id": 111111,
                "content": "第一条消息",
                "time_str": "12:00",
                "avatar_url": None
            },
            {
                "nickname": "用户B",
                "card": "",
                "user_id": 222222,
                "content": "第二条消息",
                "time_str": "12:01",
                "avatar_url": None
            }
        ]

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_with_empty_content(self):
        """测试渲染空内容消息"""
        messages = [
            {
                "nickname": "测试用户",
                "card": "",
                "user_id": 123456,
                "content": "",
                "time_str": "",
                "avatar_url": None
            }
        ]

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_with_long_content(self):
        """测试渲染长内容消息（自动换行）"""
        messages = [
            {
                "nickname": "测试用户",
                "card": "",
                "user_id": 123456,
                "content": "这是一条非常长的消息，" * 15,
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_wrap_text(self):
        """测试文本换行"""
        text = "a" * 100
        lines = self.renderer._wrap_text(text, 200)
        assert len(lines) > 1

    def test_wrap_text_with_chinese(self):
        """测试中文文本换行"""
        text = "中" * 50
        lines = self.renderer._wrap_text(text, 200)
        assert len(lines) > 1

    def test_wrap_text_with_short_text(self):
        """测试短文本不换行"""
        text = "你好"
        lines = self.renderer._wrap_text(text, 200)
        assert len(lines) == 1
        assert lines[0] == "你好"

    def test_calculate_height(self):
        """测试高度计算"""
        messages = [
            {
                "nickname": "用户A",
                "content": "短消息",
            },
            {
                "nickname": "用户B",
                "content": "这是一条比较长的消息内容",
            }
        ]
        height = self.renderer._calculate_height(messages)
        assert height > 200


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
