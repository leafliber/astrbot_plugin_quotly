"""
简单渲染测试 - pytakumi 版本
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
            "role": "admin",
            "user_id": 111111,
            "content": "第一条消息",
            "time_str": "12:00",
            "avatar_url": None
        },
        {
            "nickname": "用户B",
            "card": "群名片B",
            "title": "",
            "role": "member",
            "user_id": 222222,
            "content": "第二条消息\n包含换行",
            "time_str": "12:01",
            "avatar_url": None
        },
        {
            "nickname": "用户C",
            "card": "",
            "title": "",
            "role": "owner",
            "user_id": 333333,
            "content": "第三条消息，测试多消息渲染功能，这是一条比较长的消息用来测试气泡宽度",
            "time_str": "12:02",
            "avatar_url": None
        }
    ]

    html, css, avatar_data = renderer._build_html_and_css(messages)

    print("=" * 60)
    print("HTML 生成测试")
    print("=" * 60)
    print(f"HTML 长度: {len(html)} 字符")
    print(f"CSS 长度: {len(css)} 字符")
    print()

    checks = [
        ('class="chat-container"', "聊天容器"),
        ('class="message"', "消息容器"),
        ('class="bubble"', "气泡容器"),
        ('class="message-content"', "消息内容"),
        ("管理员", "管理员头衔"),
        ("群主", "群主头衔 (owner role)"),
        ("群名片B", "群名片"),
        ("第一条消息", "第一条消息内容"),
        ("font-family", "字体声明"),
        ("border-radius", "圆角"),
    ]

    all_passed = True
    for check_str, description in checks:
        # Check in both html and css
        found_in_html = check_str in html
        found_in_css = check_str in css
        if found_in_html or found_in_css:
            location = "HTML" if found_in_html else "CSS"
            print(f"✓ {description}: 找到 ({location})")
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


async def test_actual_render():
    renderer = QuotlyRenderer()

    print()
    print("=" * 60)
    print("实际渲染测试 (pytakumi)")
    print("=" * 60)

    messages = [
        {"type": "date_separator", "date_str": "2024-06-01"},
        {
            "nickname": "张三",
            "card": "",
            "title": "",
            "role": "owner",
            "user_id": 1001,
            "content": "大家好！这是测试消息\n多行内容",
            "time_str": "14:30",
            "avatar_url": None
        },
        {
            "nickname": "李四",
            "card": "李四名片",
            "title": "",
            "role": "member",
            "user_id": 1002,
            "content": "回复张三",
            "time_str": "14:31",
            "avatar_url": None,
            "reply_info": {
                "nickname": "张三",
                "content": "大家好！"
            }
        }
    ]

    try:
        result = await renderer.arender(messages)
        assert isinstance(result, bytes), "结果不是 bytes"
        assert result[:8] == b'\x89PNG\r\n\x1a\n', "PNG 签名不匹配"

        output_path = Path(__file__).parent.parent / "test_output.png"
        output_path.write_bytes(result)
        print(f"✓ 渲染成功: {len(result)} bytes, 保存到 {output_path}")
        return True
    except Exception as e:
        print(f"✗ 渲染失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test1_passed = asyncio.run(test_html_generation())
    test2_passed = test_escape_html()
    test3_passed = asyncio.run(test_actual_render())

    print()
    print("=" * 60)
    print("总结")
    print("=" * 60)
    if test1_passed and test2_passed and test3_passed:
        print("✓ 所有测试通过！")
        sys.exit(0)
    else:
        print("✗ 部分测试失败")
        sys.exit(1)
