"""
AstrBot Quotlin Plugin
复刻 quote-bot 项目，将 QQ 消息渲染为精美的引用图片
"""

import os
import re
import sys
import tempfile
from pathlib import Path

# 将插件目录添加到模块搜索路径
_plugin_dir = Path(__file__).parent
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))

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
        self.onebot = OneBotClient()

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
        # 设置 OneBot 客户端的 bot 对象
        self.onebot.set_event(event)

        # 解析回复消息 ID
        reply_id = self.parser.parse_reply(event)

        if reply_id is None:
            yield event.plain_result("请先回复一条消息，再使用 /q 指令")
            return

        # 解析参数（消息数量）
        message_str = event.message_str.strip()
        count = 1  # 默认只获取 1 条

        logger.debug(f"解析消息: message_str='{message_str}'")

        # 匹配 q <数字> 格式（AstrBot 已去掉 / 前缀）
        match = re.match(r'^q\s+(\d+)', message_str)
        if match:
            count = int(match.group(1))
            if count < 1:
                count = 1
            if count > 20:
                count = 20  # 限制最多 20 条

        logger.debug(f"解析结果: count={count}")

        # 获取被回复消息的内容
        msg_data = await self.onebot.get_msg(reply_id)

        if msg_data is None:
            yield event.plain_result("无法获取消息内容，请确认消息是否存在")
            return

        # 获取群号（用于后续获取群成员信息）
        # OneBot API 返回的 group_id 是整数，AstrBot 内部使用字符串
        # 统一转换为整数，因为 OneBot API 需要整数参数
        group_id = msg_data.get("group_id")
        if not group_id:
            group_id_str = getattr(event.message_obj, 'group_id', None)
            if group_id_str:
                try:
                    group_id = int(group_id_str)
                except (ValueError, TypeError):
                    group_id = None

        # 获取消息序号（用于获取历史消息）
        message_seq = msg_data.get("message_seq", 0)

        # 构建消息列表
        messages_data = [msg_data]

        logger.debug(f"准备获取历史消息: count={count}, group_id={group_id}, message_seq={message_seq}")

        # 如果需要多条消息，尝试获取历史
        if count > 1 and group_id:
            logger.debug(f"尝试获取历史消息: group_id={group_id}, message_seq={message_seq}, count={count}")
            # 使用 message_seq 获取历史消息（从这条消息开始往前获取）
            history = await self.onebot.get_history(group_id, message_seq, count)
            logger.debug(f"历史消息返回类型: {type(history)}, 内容: {history if not history or len(str(history)) < 500 else str(history)[:500] + '...'}")
            
            if history and isinstance(history, dict):
                messages_history = history.get("messages", [])
            elif history and isinstance(history, list):
                messages_history = history
            else:
                messages_history = []

            logger.debug(f"解析后的历史消息数量: {len(messages_history)}")

            if messages_history:
                # 过滤并排序消息
                # 使用 time 字段排序（从旧到新）
                filtered_messages = []
                for msg in messages_history:
                    msg_id = msg.get("message_id")
                    msg_time = msg.get("time", 0)
                    
                    # 确保 message_id 是整数
                    if isinstance(msg_id, str):
                        try:
                            msg_id = int(msg_id)
                        except (ValueError, TypeError):
                            continue
                    
                    logger.debug(f"消息 ID: {msg_id}, time: {msg_time}, reply_id: {reply_id}")
                    
                    # 只保留 message_id != reply_id 的消息（排除被回复的消息本身）
                    if msg_id is not None and msg_id != reply_id:
                        filtered_messages.append((msg_time, msg_id, msg))
                
                logger.debug(f"过滤后的消息数量: {len(filtered_messages)}")
                
                # 按 time 排序（从旧到新）
                filtered_messages.sort(key=lambda x: x[0])
                
                # 取最后 (count-1) 条消息（最接近被回复消息的）
                need_count = count - 1
                if len(filtered_messages) > need_count:
                    filtered_messages = filtered_messages[-need_count:]
                
                logger.debug(f"最终选取的历史消息数量: {len(filtered_messages)}")
                
                # 清空消息列表，按时间顺序重新添加
                messages_data = []
                # 先添加被回复的消息（消息1）
                messages_data.append(msg_data)
                # 然后添加历史消息（消息2 3 4 5）
                for _, _, msg in filtered_messages:
                    messages_data.append(msg)
                    
        logger.debug(f"总消息数量: {len(messages_data)}")

        # 渲染消息列表
        try:
            render_messages = []
            for msg_data_item in messages_data:
                sender = msg_data_item.get("sender", {})
                user_id, nickname, card, title, role = self.parser.parse_sender_info(sender)
                content, inner_reply_id = self.parser.parse_message_content(msg_data_item.get("message", []))
                time_str = self.parser.format_time_short(msg_data_item.get("time", 0))

                if not content:
                    content = "[仅包含媒体消息]"

                if not title and group_id and user_id:
                    member_info = await self.onebot.get_group_member_info(group_id, user_id)
                    if member_info:
                        title = member_info.get("title", "")

                # 处理消息内的回复
                reply_info = None
                if inner_reply_id:
                    try:
                        reply_msg = await self.onebot.get_msg(inner_reply_id)
                        if reply_msg:
                            reply_sender = reply_msg.get("sender", {})
                            reply_user_id, reply_nickname, reply_card, _, _ = self.parser.parse_sender_info(reply_sender)
                            reply_content, _ = self.parser.parse_message_content(reply_msg.get("message", []))
                            
                            # 截取回复内容预览（最多50字符）
                            if len(reply_content) > 50:
                                reply_content = reply_content[:50] + "..."
                            
                            reply_info = {
                                "nickname": reply_card if reply_card else reply_nickname,
                                "content": reply_content if reply_content else "[媒体消息]"
                            }
                    except Exception as e:
                        logger.debug(f"获取回复消息失败: {e}")

                render_messages.append({
                    "nickname": nickname,
                    "card": card,
                    "title": title,
                    "role": role,
                    "user_id": user_id,
                    "content": content,
                    "time_str": time_str,
                    "avatar_url": self.onebot.get_avatar_url(user_id),
                    "reply_info": reply_info
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
        await self.renderer.cleanup()
        logger.info("Quotlin 插件已卸载")
