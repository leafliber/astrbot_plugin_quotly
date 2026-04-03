"""
OneBot 客户端单元测试
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.onebot_client import OneBotClient


class MockContext:
    """模拟 AstrBot Context"""
    def __init__(self):
        self.called_api = None
        self.api_params = None
        self.api_result = None

    async def request(self, api_name: str, params: dict):
        """模拟 API 请求"""
        self.called_api = api_name
        self.api_params = params
        return self.api_result


class TestOneBotClient:
    """OneBotClient 测试类"""

    def setup_method(self):
        """每个测试方法执行前的setup"""
        self.mock_context = MockContext()
        self.client = OneBotClient(self.mock_context)

    def test_get_avatar_url_default_size(self):
        """测试获取默认尺寸头像 URL"""
        qq = 123456
        url = self.client.get_avatar_url(qq)

        assert f"dst_uin={qq}" in url
        assert "spec=640" in url

    def test_get_avatar_url_custom_size(self):
        """测试获取自定义尺寸头像 URL"""
        qq = 123456
        size = 100
        url = self.client.get_avatar_url(qq, size=size)

        assert f"dst_uin={qq}" in url
        assert f"spec={size}" in url

    def test_get_msg_success(self):
        """测试获取消息成功"""
        expected_msg = {
            "time": 1234567890,
            "message_type": "group",
            "message_id": 12345,
            "sender": {"user_id": 111, "nickname": "测试"},
            "message": [{"type": "text", "data": {"text": "你好"}}]
        }
        self.mock_context.api_result = expected_msg

        result = asyncio.run(self.client.get_msg(12345))

        assert self.mock_context.called_api == "get_msg"
        assert self.mock_context.api_params == {"message_id": 12345}
        assert result == expected_msg

    def test_get_msg_failure(self):
        """测试获取消息失败"""
        self.mock_context.api_result = None

        result = asyncio.run(self.client.get_msg(99999))

        assert result is None

    def test_get_stranger_info_success(self):
        """测试获取陌生人信息成功"""
        expected_info = {
            "user_id": 123456,
            "nickname": "陌生人",
            "sex": "unknown",
            "age": 18
        }
        self.mock_context.api_result = expected_info

        result = asyncio.run(self.client.get_stranger_info(123456))

        assert self.mock_context.called_api == "get_stranger_info"
        assert self.mock_context.api_params == {"user_id": 123456}
        assert result == expected_info

    def test_get_stranger_info_failure(self):
        """测试获取陌生人信息失败"""
        self.mock_context.api_result = None

        result = asyncio.run(self.client.get_stranger_info(99999))

        assert result is None

    def test_get_history_success(self):
        """测试获取消息历史成功"""
        expected_history = [
            {"message_id": 123, "message": "消息1"},
            {"message_id": 124, "message": "消息2"},
        ]
        self.mock_context.api_result = expected_history

        result = asyncio.run(self.client.get_history(123456, 100, 10))

        assert self.mock_context.called_api == "get_history"
        assert self.mock_context.api_params == {"group_id": 123456, "start_message_id": 100, "count": 10}
        assert result == expected_history

    def test_get_history_failure(self):
        """测试获取消息历史失败"""
        self.mock_context.api_result = None

        result = asyncio.run(self.client.get_history(123456, 100, 10))

        assert result is None

    def test_get_group_member_info_success(self):
        """测试获取群成员信息成功"""
        expected_info = {
            "user_id": 123456,
            "nickname": "群友",
            "title": "群主"
        }
        self.mock_context.api_result = expected_info

        result = asyncio.run(self.client.get_group_member_info(123456, 789))

        assert self.mock_context.called_api == "get_group_member_info"
        assert self.mock_context.api_params == {"group_id": 123456, "user_id": 789}
        assert result == expected_info

    def test_get_group_member_info_failure(self):
        """测试获取群成员信息失败"""
        self.mock_context.api_result = None

        result = asyncio.run(self.client.get_group_member_info(123456, 99999))

        assert result is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
