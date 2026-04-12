"""
渲染器单元测试
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.quotly_renderer import QuotlyRenderer


class TestQuotlyRenderer:
    """QuotlyRenderer 测试类"""

    def setup_method(self):
        """每个测试方法执行前的setup"""
        self.renderer = QuotlyRenderer()

    def teardown_method(self):
        """每个测试方法执行后的清理"""
        pass

    def test_render_single_message(self):
        """测试渲染单条消息"""
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

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_with_empty_content(self):
        """测试渲染空内容消息"""
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

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_with_long_content(self):
        """测试渲染长内容消息"""
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

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_with_title(self):
        """测试渲染带头衔的消息"""
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

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_with_multiline_content(self):
        """测试渲染多行消息（测试气泡宽度自适应）"""
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

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_render_with_special_characters(self):
        """测试渲染包含特殊字符的消息"""
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

        result = self.renderer.render(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_async_render_single_message(self):
        """测试异步渲染单条消息"""
        messages = [
            {
                "nickname": "测试用户",
                "card": "",
                "title": "",
                "user_id": 123456,
                "content": "异步渲染测试",
                "time_str": "12:30",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    async def test_async_render_multiple_messages(self):
        """测试异步渲染多条消息"""
        messages = [
            {
                "nickname": "用户A",
                "card": "",
                "title": "管理员",
                "user_id": 111111,
                "content": "第一条消息",
                "time_str": "12:00",
                "avatar_url": None
            },
            {
                "nickname": "用户B",
                "card": "群名片B",
                "title": "",
                "user_id": 222222,
                "content": "第二条消息\n包含换行",
                "time_str": "12:01",
                "avatar_url": None
            },
            {
                "nickname": "用户C",
                "card": "",
                "title": "群主",
                "user_id": 333333,
                "content": "第三条消息，测试多消息渲染功能",
                "time_str": "12:02",
                "avatar_url": None
            }
        ]

        result = await self.renderer.arender(messages)

        assert isinstance(result, bytes)
        assert result[:8] == b'\x89PNG\r\n\x1a\n'

    def test_escape_html(self):
        """测试 HTML 特殊字符转义"""
        test_cases = [
            ("<test>", "&lt;test&gt;"),
            ("a & b", "a &amp; b"),
            ('quote "test"', "quote &quot;test&quot;"),
        ]

        for input_text, expected in test_cases:
            result = self.renderer._escape_html(input_text)
            assert result == expected, f"Input: {input_text}, Expected: {expected}, Got: {result}"

    def test_escape_html_with_empty_string(self):
        """测试空字符串转义"""
        result = self.renderer._escape_html("")
        assert result == ""

    def test_escape_html_with_normal_text(self):
        """测试普通文本（无特殊字符）转义"""
        result = self.renderer._escape_html("你好，世界！")
        assert result == "你好，世界！"

    def test_build_html_structure(self):
        """测试 HTML 结构构建"""
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

        html = self.renderer._build_html(messages)

        assert "<!DOCTYPE html>" in html
        assert 'class="chat-container"' in html
        assert 'class="message left"' in html
        assert 'class="bubble"' in html
        assert '<span class="nickname">测试用户</span>' in html
        assert '<div class="message-content">消息内容</div>' in html
        assert '专属头衔' in html

    def test_build_html_with_card(self):
        """测试 HTML 结构构建（有群名片）"""
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

        html = self.renderer._build_html(messages)

        assert "<!DOCTYPE html>" in html
        assert 'class="chat-container"' in html
        assert 'class="message left"' in html
        assert 'class="bubble"' in html
        # 有群名片时显示群名片
        assert '<span class="nickname">群名片</span>' in html
        assert '<div class="message-content">消息内容</div>' in html
        assert '专属头衔' in html


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
