"""
文本处理工具
"""

from typing import List


def truncate_text(text: str, max_length: int = 500, suffix: str = "...") -> str:
    """
    截断过长的文本

    Args:
        text: 原始文本
        max_length: 最大长度
        suffix: 截断后缀

    Returns:
        截断后的文本
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def escape_markdown(text: str) -> str:
    """
    转义 Markdown 特殊字符

    Args:
        text: 原始文本

    Returns:
        转义后的文本
    """
    special_chars = ['\\', '`', '*', '_', '{', '}', '[', ']', '(', ')', '#', '+', '-', '.', '!']
    for char in special_chars:
        text = text.replace(char, '\\' + char)
    return text


def split_long_message(text: str, max_length: int = 500) -> List[str]:
    """
    分割长消息

    Args:
        text: 原始文本
        max_length: 每段最大长度

    Returns:
        分割后的文本列表
    """
    if len(text) <= max_length:
        return [text] if text else []

    lines = []
    current = ""

    for char in text:
        if char == '\n' and len(current) + 1 > max_length:
            lines.append(current)
            current = ""
        elif len(current) >= max_length:
            lines.append(current)
            current = char
        else:
            current += char

    if current:
        lines.append(current)

    return lines
