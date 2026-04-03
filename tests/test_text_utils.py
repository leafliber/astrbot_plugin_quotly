"""
文本工具单元测试
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.text_utils import (
    truncate_text,
    escape_markdown,
    split_long_message
)


class TestTextUtils:
    """TextUtils 测试类"""

    def test_truncate_text_short(self):
        """测试不需截断的文本"""
        text = "短文本"
        result = truncate_text(text, max_length=100)
        assert result == "短文本"

    def test_truncate_text_long(self):
        """测试需要截断的文本"""
        text = "a" * 100
        result = truncate_text(text, max_length=50)
        assert len(result) == 50
        assert result.endswith("...")

    def test_truncate_text_exact_length(self):
        """测试刚好等于最大长度的文本"""
        text = "a" * 50
        result = truncate_text(text, max_length=50)
        assert result == text
        assert not result.endswith("...")

    def test_truncate_text_custom_suffix(self):
        """测试自定义截断后缀"""
        text = "a" * 100
        result = truncate_text(text, max_length=50, suffix="***")
        assert result.endswith("***")

    def test_escape_markdown_normal(self):
        """测试普通文本（无特殊字符）"""
        text = "你好世界"
        result = escape_markdown(text)
        assert result == "你好世界"

    def test_escape_markdown_with_special_chars(self):
        """测试包含特殊字符的文本"""
        text = "*bold* and _italic_"
        result = escape_markdown(text)
        assert "\\*" in result
        assert "\\_" in result

    def test_escape_markdown_with_code_chars(self):
        """测试包含代码字符的文本"""
        text = "use `code` and ```block```"
        result = escape_markdown(text)
        assert "\\`" in result

    def test_split_long_message_single(self):
        """测试短消息不分割"""
        text = "短消息"
        result = split_long_message(text, max_length=100)
        assert len(result) == 1
        assert result[0] == "短消息"

    def test_split_long_message_multiple(self):
        """测试长消息分割"""
        text = "a" * 600
        result = split_long_message(text, max_length=200)
        assert len(result) > 1

    def test_split_long_message_with_newlines(self):
        """测试包含换行符的消息分割"""
        text = "line1\n" + "a" * 300
        result = split_long_message(text, max_length=200)
        # 换行符处也应该分割
        assert len(result) >= 2

    def test_split_long_message_empty(self):
        """测试空消息"""
        result = split_long_message("", max_length=100)
        assert result == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
