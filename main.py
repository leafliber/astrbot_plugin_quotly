"""
AstrBot Quotlin Plugin
复刻 quote-bot 项目，将 QQ 消息渲染为精美的引用图片
"""

import os
import re
import tempfile
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp

from core.onebot_client import OneBotClient
from core.message_parser import MessageParser
from core.quotly_renderer import QuotlyRenderer


@register("quotly", "Leafiber", "将消息渲染为精美的引用图片", "1.0.0")
class QuotlinPlugin(Star):
    """引用消息渲染插件"""

    def __init__(self, context: Context):
        super().__init__(context)
        self.parser = MessageParser()
        self.onebot = OneBotClient(context)

        # 初始化渲染器
        font_dir = Path(__file__).parent / "assets" / "fonts"
        self.renderer = QuotlyRenderer(str(font_dir))

        logger.info("Quotlin 插件已加载")

    @filter.command("q")
    async def quote_command(self, event: AstrMessageEvent):
        """
        /q - Create a quote from replied message
        /q <number> - Create quote from multiple messages (includes this message and previous <number>-1 messages)
        """
        # 解析回复消息 ID
        reply_id = self.parser.parse_reply(event)

        if reply_id is None:
            yield event.plain_result("请先回复一条消息，再使用 /q 指令")
            return

        # 解析参数（消息数量）
        message_str = event.message_str.strip()
        count = 1  # 默认只获取 1 条

        # 匹配 /q <数字> 格式
        match = re.match(r'^/q\s+(\d+)$', message_str)
        if match:
            count = int(match.group(1))
            if count < 1:
                count = 1
            if count > 20:
                count = 20  # 限制最多 20 条

        # 获取被回复消息的内容
        msg_data = await self.onebot.get_msg(reply_id)

        if msg_data is None:
            yield event.plain_result("无法获取消息内容，请确认消息是否存在")
            return

        # 构建消息列表
        messages_data = [msg_data]

        # 如果需要多条消息，尝试获取历史
        if count > 1:
            # 尝试获取更多消息（通过 get_history API 或其他方式）
            group_id = msg_data.get("group_id") or event.unified_msg_origin
            if group_id:
                history = await self.onebot.get_history(group_id, reply_id, count)
                if history:
                    # 过滤出 reply_id 之前的消息
                    for msg in history:
                        if msg.get("message_id") < reply_id:
                            messages_data.insert(0, msg)
                            if len(messages_data) >= count:
                                break

        # 渲染消息列表
        try:
            render_messages = []
            for msg_data_item in messages_data:
                sender = msg_data_item.get("sender", {})
                user_id, nickname, card = self.parser.parse_sender_info(sender)
                content = self.parser.parse_message_content(msg_data_item.get("message", []))
                time_str = self.parser.format_time_short(msg_data_item.get("time", 0))

                if not content:
                    content = "[仅包含媒体消息]"

                # 获取群头衔（如果有的话）
                title = ""
                if group_id and user_id:
                    member_info = await self.onebot.get_group_member_info(group_id, user_id)
                    if member_info:
                        title = member_info.get("title", "")

                render_messages.append({
                    "nickname": nickname,
                    "card": card,
                    "title": title,
                    "user_id": user_id,
                    "content": content,
                    "time_str": time_str,
                    "avatar_url": self.onebot.get_avatar_url(user_id)
                })

            # 渲染图片
            png_data = await self.renderer.arender(render_messages)

            # 保存到临时文件
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(png_data)
                temp_path = f.name

            try:
                # 发送图片
                yield event.chain_result([Comp.Image.fromFileSystem(temp_path)])
            finally:
                # 清理临时文件
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        except Exception as e:
            logger.error(f"渲染失败: {e}")
            yield event.plain_result(f"渲染失败: {str(e)}")

    async def terminate(self):
        """插件卸载时调用"""
        await self.renderer.close()
        logger.info("Quotlin 插件已卸载")
