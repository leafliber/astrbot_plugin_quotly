"""
渲染器单元测试
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.quotly_renderer import QuotlyRenderer


class TestQuotlyRenderer:

    def setup_method(self):
        self.renderer = QuotlyRenderer()

    def teardown_method(self):
        pass

    async def test_render_single_message(self):
        messages = [
            {
                "nickname": "测试用户",
                "card": "群名片",
                "title": "",
                "user_id": 123456,
                "content": "这是一条测试消息",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_render_multiple_messages(self):
        messages = [
            {
                "nickname": "用户A",
                "card": "",
                "title": "",
                "user_id": 111111,
                "content": "第一条消息",
                "time_str": "12:00",
                "avatar_url": None
            },
            {
                "nickname": "用户B",
                "card": "",
                "title": "",
                "user_id": 222222,
                "content": "第二条消息",
                "time_str": "12:01",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_render_with_empty_content(self):
        messages = [
            {
                "nickname": "测试用户",
                "card": "",
                "title": "",
                "user_id": 123456,
                "content": "",
                "time_str": "",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_render_with_long_content(self):
        messages = [
            {
                "nickname": "测试用户",
                "card": "",
                "title": "",
                "user_id": 123456,
                "content": "这是一条非常长的消息，" * 20,
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_render_with_title(self):
        messages = [
            {
                "nickname": "测试用户",
                "card": "群名片",
                "title": "专属头衔",
                "user_id": 123456,
                "content": "这是一条带头衔的消息",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_render_with_multiline_content(self):
        messages = [
            {
                "nickname": "测试用户",
                "card": "",
                "title": "",
                "user_id": 123456,
                "content": "第一行\n第二行，这一行比较长\n第三行",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_render_with_special_characters(self):
        messages = [
            {
                "nickname": "测试<用户>",
                "card": "群&名片",
                "title": "头\"衔\"",
                "user_id": 123456,
                "content": "消息包含<特殊>字符&\"引号\"",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_escape_html(self):
        test_cases = [
            ("<test>", "&lt;test&gt;"),
            ("a & b", "a &amp; b"),
            ('quote "test"', "quote &quot;test&quot;"),
        ]

        for input_text, expected in test_cases:
            result = self.renderer._escape_html(input_text)
            assert result == expected, f"Input: {input_text}, Expected: {expected}, Got: {result}"

    def test_escape_html_with_empty_string(self):
        result = self.renderer._escape_html("")
        assert result == ""

    def test_escape_html_with_normal_text(self):
        result = self.renderer._escape_html("你好，世界！")
        assert result == "你好，世界！"

    async def test_build_html_structure(self):
        messages = [
            {
                "nickname": "测试用户",
                "card": "",
                "title": "专属头衔",
                "user_id": 123456,
                "content": "消息内容",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        html = await self.renderer._build_html_async(messages)

        assert "<!DOCTYPE html>" in html
        assert 'class="chat-container"' in html
        assert 'class="message left"' in html
        assert 'class="bubble"' in html
        assert '<span class="nickname">测试用户</span>' in html
        assert '<div class="message-content">消息内容</div>' in html
        assert '专属头衔' in html

    async def test_build_html_with_card(self):
        messages = [
            {
                "nickname": "测试用户",
                "card": "群名片",
                "title": "专属头衔",
                "user_id": 123456,
                "content": "消息内容",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        html = await self.renderer._build_html_async(messages)

        assert "<!DOCTYPE html>" in html
        assert 'class="chat-container"' in html
        assert 'class="message left"' in html
        assert 'class="bubble"' in html
        assert '<span class="nickname">群名片</span>' in html
        assert '<div class="message-content">消息内容</div>' in html
        assert '专属头衔' in html


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
