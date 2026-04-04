#!/usr/bin/env python3
"""
渲染测试用例
测试 QuotlyRenderer 的渲染功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from core.quotly_renderer import QuotlyRenderer


async def test_render():
    """测试渲染功能"""
    
    # 初始化渲染器
    font_dir = Path(__file__).parent / "assets" / "fonts"
    renderer = QuotlyRenderer(str(font_dir))
    
    # 测试消息列表
    test_messages = [
        {
            "nickname": "张三",
            "card": "",
            "title": "",
            "role": "owner",
            "user_id": 123456789,
            "content": "这是群主的消息，测试群主头衔显示",
            "time_str": "12:00",
            "avatar_url": ""
        },
        {
            "nickname": "李四",
            "card": "管理员小李",
            "title": "技术大佬",
            "role": "admin",
            "user_id": 987654321,
            "content": "这是管理员的消息，带有专属头衔",
            "time_str": "12:01",
            "avatar_url": ""
        },
        {
            "nickname": "王五",
            "card": "",
            "title": "",
            "role": "admin",
            "user_id": 111222333,
            "content": "这是管理员的消息，没有专属头衔",
            "time_str": "12:02",
            "avatar_url": ""
        },
        {
            "nickname": "赵六",
            "card": "",
            "title": "VIP会员",
            "role": "member",
            "user_id": 444555666,
            "content": "这是普通成员的消息，带有专属头衔",
            "time_str": "12:03",
            "avatar_url": ""
        },
        {
            "nickname": "钱七",
            "card": "",
            "title": "",
            "role": "member",
            "user_id": 777888999,
            "content": "这是普通成员的消息，没有专属头衔。测试长文本换行：这是一段很长的文本，用来测试气泡宽度自适应功能，看看是否能够正确处理换行和宽度计算。",
            "time_str": "12:04",
            "avatar_url": ""
        },
        {
            "nickname": "孙八",
            "card": "",
            "title": "",
            "role": "member",
            "user_id": 123123123,
            "content": "测试字母和数字：Helloasdasdadasd World好的好的!",
            "time_str": "12:05",
            "avatar_url": ""
        },
        {
            "nickname": "周九",
            "card": "",
            "title": "",
            "role": "member",
            "user_id": 456456456,
            "content": "测试标点符号：，。！？；：""''【】（）《》、——…～@#￥%&*+-=/\\|",
            "time_str": "12:06",
            "avatar_url": ""
        },
        {
            "nickname": "吴十",
            "card": "",
            "title": "",
            "role": "member",
            "user_id": 789789789,
            "content": "测试图片：[图片](https://q.qlogo.cn/headimg_dl?dst_uin=10002&spec=100)",
            "time_str": "12:07",
            "avatar_url": ""
        },
        {
            "nickname": "郑十一",
            "card": "",
            "title": "",
            "role": "member",
            "user_id": 321321321,
            "content": "这是一条回复消息",
            "time_str": "12:08",
            "avatar_url": "",
            "reply_info": {
                "nickname": "张三",
                "content": "这是群主的消息，测试群主头衔显示"
            }
        },
        {
            "nickname": "王十二",
            "card": "",
            "title": "",
            "role": "member",
            "user_id": 654654654,
            "content": "回复图片消息：[图片](https://q.qlogo.cn/headimg_dl?dst_uin=10002&spec=100)",
            "time_str": "12:09",
            "avatar_url": "",
            "reply_info": {
                "nickname": "吴十",
                "content": "测试图片：[图片]"
            }
        }
    ]
    
    print("开始渲染测试...")
    print(f"测试消息数量: {len(test_messages)}")
    
    try:
        # 渲染图片
        png_data = await renderer.arender(test_messages)
        
        # 保存到文件
        output_path = Path(__file__).parent / "test_output.png"
        with open(output_path, 'wb') as f:
            f.write(png_data)
        
        print(f"渲染成功！")
        print(f"输出文件: {output_path}")
        print(f"文件大小: {len(png_data)} bytes")
        
        # 清理浏览器实例
        await renderer.cleanup()
        
    except Exception as e:
        print(f"渲染失败: {e}")
        import traceback
        traceback.print_exc()
        await renderer.cleanup()


if __name__ == "__main__":
    asyncio.run(test_render())
