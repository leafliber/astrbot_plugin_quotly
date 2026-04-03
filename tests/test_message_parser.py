"""
消息解析器单元测试
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.message_parser import MessageParser


class MockSegment:
    """模拟消息段对象"""
    def __init__(self, seg_type: str, data: dict):
        self.type = seg_type
        self.data = data


class MockEvent:
    """模拟事件对象"""
    def __init__(self, message_obj):
        self.message_obj = message_obj


class TestMessageParser:
    """MessageParser 测试类"""

    def setup_method(self):
        """每个测试方法执行前的setup"""
        self.parser = MessageParser()

    def test_parse_reply_with_reply_segment(self):
        """测试解析包含 reply 消息段的事件"""
        # 模拟一个包含 reply 段的消息事件
        segments = [
            MockSegment("text", {"text": "这是一条消息"}),
            MockSegment("reply", {"id": "12345"}),
        ]
        event = MockEvent(segments)

        result = self.parser.parse_reply(event)

        assert result == 12345

    def test_parse_reply_without_reply_segment(self):
        """测试解析不包含 reply 消息段的事件"""
        segments = [
            MockSegment("text", {"text": "这是一条普通消息"}),
        ]
        event = MockEvent(segments)

        result = self.parser.parse_reply(event)

        assert result is None

    def test_parse_reply_with_empty_message_obj(self):
        """测试解析空消息对象"""
        event = MockEvent([])

        result = self.parser.parse_reply(event)

        assert result is None

    def test_parse_reply_with_none_message_obj(self):
        """测试解析 None 消息对象"""
        event = MockEvent(None)

        result = self.parser.parse_reply(event)

        assert result is None

    def test_parse_sender_info(self):
        """测试解析发送者信息"""
        sender = {
            "user_id": 123456,
            "nickname": "测试用户",
            "card": "群名片"
        }

        user_id, nickname, card = self.parser.parse_sender_info(sender)

        assert user_id == 123456
        assert nickname == "测试用户"
        assert card == "群名片"

    def test_parse_sender_info_with_empty_card(self):
        """测试解析发送者信息（无群名片）"""
        sender = {
            "user_id": 123456,
            "nickname": "测试用户"
        }

        user_id, nickname, card = self.parser.parse_sender_info(sender)

        assert user_id == 123456
        assert nickname == "测试用户"
        assert card == ""

    def test_parse_message_content_with_text(self):
        """测试解析纯文本消息"""
        message = [
            {"type": "text", "data": {"text": "你好，世界"}}
        ]

        result = self.parser.parse_message_content(message)

        assert result == "你好，世界"

    def test_parse_message_content_with_multiple_segments(self):
        """测试解析多消息段"""
        message = [
            {"type": "text", "data": {"text": "你好，"}},
            {"type": "at", "data": {"name": "某人"}},
            {"type": "text", "data": {"text": "！这是图片："}},
            {"type": "image", "data": {"file": "xxx.jpg"}},
        ]

        result = self.parser.parse_message_content(message)

        assert "你好，" in result
        assert "@某人" in result
        assert "这是图片：" in result
        assert "[图片]" in result

    def test_parse_message_content_with_empty_message(self):
        """测试解析空消息"""
        result = self.parser.parse_message_content([])

        assert result == ""

    def test_format_time(self):
        """测试时间格式化"""
        import time
        timestamp = int(time.mktime(time.strptime("2024-01-01 12:30:45", "%Y-%m-%d %H:%M:%S")))

        result = self.parser.format_time(timestamp)

        assert "2024-01-01" in result
        assert "12:30:45" in result

    def test_format_time_short(self):
        """测试短时间格式化"""
        import time
        timestamp = int(time.mktime(time.strptime("2024-01-01 12:30:45", "%Y-%m-%d %H:%M:%S")))

        result = self.parser.format_time_short(timestamp)

        assert result == "12:30"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
