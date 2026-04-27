"""
简单渲染测试 - 不需要 playwright
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.quotly_renderer import QuotlyRenderer


async def test_html_generation():
    renderer = QuotlyRenderer()

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
            "content": "第三条消息，测试多消息渲染功能，这是一条比较长的消息用来测试气泡宽度自适应",
            "time_str": "12:02",
            "avatar_url": None
        }
    ]

    html = await renderer._build_html_async(messages)

    print("=" * 60)
    print("HTML 生成测试")
    print("=" * 60)
    print(f"HTML 长度: {len(html)} 字符")
    print()

    checks = [
        ("<!DOCTYPE html>", "HTML 文档类型声明"),
        ('class="chat-container"', "聊天容器"),
        ('class="message left"', "消息容器"),
        ('class="bubble"', "气泡容器"),
        ('class="message-content"', "消息内容"),
        ("管理员", "管理员头衔"),
        ("群主", "群主头衔"),
        ("群名片B", "群名片"),
        ("第一条消息", "第一条消息内容"),
        ("adjustBubbleWidth", "气泡宽度调整脚本"),
    ]

    all_passed = True
    for check_str, description in checks:
        if check_str in html:
            print(f"✓ {description}: 找到")
        else:
            print(f"✗ {description}: 未找到")
            all_passed = False

    print()
    print("=" * 60)

    if all_passed:
        print("✓ 所有检查通过！")
    else:
        print("✗ 部分检查失败")

    return all_passed


def test_escape_html():
    renderer = QuotlyRenderer()

    print()
    print("=" * 60)
    print("HTML 转义测试")
    print("=" * 60)

    test_cases = [
        ("<test>", "&lt;test&gt;"),
        ("a & b", "a &amp; b"),
        ('quote "test"', "quote &quot;test&quot;"),
        ("正常文本", "正常文本"),
    ]

    all_passed = True
    for input_text, expected in test_cases:
        result = renderer._escape_html(input_text)
        if result == expected:
            print(f"✓ 输入: {input_text!r} -> 输出: {result!r}")
        else:
            print(f"✗ 输入: {input_text!r} -> 期望: {expected!r}, 实际: {result!r}")
            all_passed = False

    print("=" * 60)

    if all_passed:
        print("✓ 所有转义测试通过！")
    else:
        print("✗ 部分转义测试失败")

    return all_passed


if __name__ == "__main__":
    test1_passed = asyncio.run(test_html_generation())
    test2_passed = test_escape_html()

    print()
    print("=" * 60)
    print("总结")
    print("=" * 60)
    if test1_passed and test2_passed:
        print("✓ 所有测试通过！")
        sys.exit(0)
    else:
        print("✗ 部分测试失败")
        sys.exit(1)
