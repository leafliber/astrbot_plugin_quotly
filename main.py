"""
AstrBot Quotlin Plugin
复刻 quote-bot 项目，将 QQ 消息渲染为精美的引用图片
"""

import os
import tempfile
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp

from core.onebot_client import OneBotClient
from core.message_parser import MessageParser
from core.quotly_renderer import QuotlyRenderer


@register("quotly", "Quotlin", "将消息渲染为精美的引用图片", "1.0.0")
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

    @filter.command("quote")
    async def quote_command(self, event: AstrMessageEvent):
        """
        /quote - 生成引用消息图片
        用法：回复某条消息并发送 /quote
        """
        # 解析回复消息 ID
        reply_id = self.parser.parse_reply(event)

        if reply_id is None:
            yield event.plain_result("请先回复一条消息，再使用 /quote 指令")
            return

        # 获取被回复消息的内容
        msg_data = await self.onebot.get_msg(reply_id)

        if msg_data is None:
            yield event.plain_result("无法获取消息内容，请确认消息是否存在")
            return

        # 解析消息数据
        sender = msg_data.get("sender", {})
        user_id, nickname, card = self.parser.parse_sender_info(sender)
        content = self.parser.parse_message_content(msg_data.get("message", []))
        time_str = self.parser.format_time_short(msg_data.get("time", 0))

        if not content:
            content = "[仅包含媒体消息]"

        # 构建消息数据
        message_data = {
            "nickname": nickname,
            "card": card,
            "user_id": user_id,
            "content": content,
            "time_str": time_str,
            "avatar_url": self.onebot.get_avatar_url(user_id)
        }

        try:
            # 渲染图片
            png_data = self.renderer.render([message_data])

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

    @filter.command("q")
    async def quote_short_command(self, event: AstrMessageEvent):
        """
        /q - /quote 的简短别名
        """
        # 直接调用 quote_command 的逻辑
        await self.quote_command(event)

    async def terminate(self):
        """插件卸载时调用"""
        logger.info("Quotlin 插件已卸载")
