"""
消息提供者
统一消息获取逻辑，优先使用 message_recorder 插件，降级到 OneBot API
"""

from dataclasses import dataclass
from typing import Optional, List, Any
from astrbot.api import logger


@dataclass
class RenderMessage:
    """渲染用的消息数据结构"""
    user_id: int
    nickname: str
    card: str
    title: str
    role: str
    content: str
    time_str: str
    timestamp: int
    avatar_url: str
    reply_info: Optional[dict] = None
    raw_message: Optional[dict] = None


class MessageProvider:
    """消息提供者，统一消息获取逻辑"""

    def __init__(self, context: Any, onebot_client: Any, message_parser: Any):
        self.context = context
        self.onebot = onebot_client
        self.parser = message_parser
        self._mr_api = None

    async def get_message_recorder_api(self) -> Optional[Any]:
        """
        获取 message_recorder 插件的 API

        Returns:
            message_recorder API 实例，如果不可用则返回 None
        """
        try:
            recorder = self.context.get_registered_star("astrbot_plugin_message_recorder")
            logger.debug(f"get_registered_star 返回: {recorder}, 类型: {type(recorder)}")
            
            if recorder is None:
                logger.debug("message_recorder 插件未注册，可能未安装或未启用")
                return None
            
            logger.debug(f"hasattr(recorder, 'get_api'): {hasattr(recorder, 'get_api')}")
            
            if hasattr(recorder, "get_api"):
                api = recorder.get_api()
                logger.debug(f"get_api() 返回: {api}, 类型: {type(api)}")
                
                if api:
                    self._mr_api = api
                    logger.info("message_recorder 插件 API 可用，将优先使用其获取消息")
                    return api
                else:
                    logger.debug("get_api() 返回 None，插件可能尚未完成初始化")
            else:
                logger.debug("recorder 没有 get_api 方法")
                
        except Exception as e:
            logger.warning(f"获取 message_recorder API 失败: {e}")
            import traceback
            logger.debug(f"错误堆栈:\n{traceback.format_exc()}")

        return None

    def _format_time_short(self, timestamp: int) -> str:
        """格式化时间戳为短格式"""
        if not timestamp:
            return ""
        import time
        try:
            return time.strftime("%H:%M", time.localtime(timestamp))
        except Exception:
            return ""

    def _get_avatar_url(self, user_id: int, platform: str = "qq") -> str:
        """
        获取用户头像 URL

        Args:
            user_id: 用户 ID
            platform: 平台名称

        Returns:
            头像 URL
        """
        if platform == "qq" or not platform:
            return f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
        elif platform == "telegram":
            return f"https://ui-avatars.com/api/?name={user_id}&background=random"
        elif platform == "discord":
            return f"https://cdn.discordapp.com/embed/avatars/0.png"
        else:
            return f"https://ui-avatars.com/api/?name={user_id}&background=random"

    def _extract_qq_sender_info(self, raw_message: dict) -> tuple:
        """
        从原始消息中提取 QQ 发送者信息

        Args:
            raw_message: OneBot11 格式的原始消息

        Returns:
            (card, title, role)
        """
        if not raw_message or not isinstance(raw_message, dict):
            return "", "", "member"

        sender = raw_message.get("sender", {})
        if not sender:
            return "", "", "member"

        return (
            sender.get("card", ""),
            sender.get("title", ""),
            sender.get("role", "member")
        )

    async def _get_qq_sender_info_via_onebot(self, group_id: int, user_id: int) -> tuple:
        """
        通过 OneBot API 获取 QQ 发送者信息

        Args:
            group_id: 群号
            user_id: 用户 QQ 号

        Returns:
            (card, title, role)
        """
        if not self.onebot:
            return "", "", "member"

        try:
            member_info = await self.onebot.get_group_member_info(group_id, user_id)
            if member_info:
                return (
                    member_info.get("card", ""),
                    member_info.get("title", ""),
                    member_info.get("role", "member")
                )
        except Exception as e:
            logger.warning(f"获取群成员信息失败: group_id={group_id}, user_id={user_id}, 错误: {e}")

        return "", "", "member"

    async def convert_mr_to_render(
        self,
        mr_message: Any,
        group_id: Optional[int] = None,
        use_raw_message: bool = True
    ) -> RenderMessage:
        """
        将 message_recorder 的 MessageRecord 转换为 RenderMessage

        Args:
            mr_message: MessageRecord 实例
            group_id: 群号（用于获取群成员信息）
            use_raw_message: 是否尝试从 raw_message 提取 QQ 专属字段

        Returns:
            RenderMessage 实例
        """
        user_id = int(mr_message.sender_id) if mr_message.sender_id else 0
        timestamp = mr_message.timestamp // 1000 if mr_message.timestamp else 0
        platform = mr_message.platform or "qq"

        card = ""
        title = ""
        role = "member"

        if use_raw_message:
            raw = mr_message.get_raw_message_dict()
            if raw:
                card, title, role = self._extract_qq_sender_info(raw)
                logger.debug(f"从 raw_message 提取发送者信息: card={card}, title={title}, role={role}")

        if not card and not title and group_id and platform == "qq":
            card, title, role = await self._get_qq_sender_info_via_onebot(group_id, user_id)
            logger.debug(f"从 OneBot API 获取发送者信息: card={card}, title={title}, role={role}")

        content = mr_message.message_str or ""
        if not content:
            chain = mr_message.get_message_chain_list()
            if chain:
                content = self._parse_message_chain_to_text(chain)

        return RenderMessage(
            user_id=user_id,
            nickname=mr_message.sender_name or "",
            card=card,
            title=title,
            role=role,
            content=content,
            time_str=self._format_time_short(timestamp),
            timestamp=timestamp,
            avatar_url=self._get_avatar_url(user_id, platform),
            raw_message=mr_message.get_raw_message_dict() if use_raw_message else None
        )

    def _parse_message_chain_to_text(self, chain: list) -> str:
        """
        将消息链转换为纯文本

        Args:
            chain: 消息链列表

        Returns:
            纯文本内容
        """
        if not chain:
            return ""

        text_parts = []
        for segment in chain:
            if isinstance(segment, dict):
                seg_type = segment.get("type", "")
                seg_data = segment.get("data", {})

                if seg_type == "text":
                    text_parts.append(seg_data.get("text", ""))
                elif seg_type == "image":
                    url = seg_data.get("url", "") or seg_data.get("file", "")
                    text_parts.append(f"[图片]({url})" if url else "[图片]")
                elif seg_type == "face":
                    name = seg_data.get("name", "") or f"表情{seg_data.get('id', '')}"
                    text_parts.append(f"[{name}]")
                elif seg_type == "mface":
                    url = seg_data.get("url", "")
                    text_parts.append(f"[图片]({url})" if url else f"[{seg_data.get('summary', '表情')}]")
                elif seg_type == "record":
                    text_parts.append("[语音]")
                elif seg_type == "video":
                    text_parts.append("[视频]")
                elif seg_type == "at":
                    text_parts.append(f"@{seg_data.get('name', '')}")

        return "".join(text_parts).strip()

    async def get_message_by_id(
        self,
        message_id: int,
        group_id: Optional[int] = None
    ) -> Optional[dict]:
        """
        获取单条消息

        Args:
            message_id: 消息 ID
            group_id: 群号

        Returns:
            消息数据字典，包含 OneBot11 格式的消息信息
        """
        mr_api = await self.get_message_recorder_api()

        if mr_api:
            try:
                mr_msg = await mr_api.get_by_id(int(message_id))
                if mr_msg:
                    render_msg = await self.convert_mr_to_render(mr_msg, group_id)
                    raw = mr_msg.get_raw_message_dict() or {}

                    return {
                        "message_id": mr_msg.message_id,
                        "group_id": int(mr_msg.group_id) if mr_msg.group_id else None,
                        "sender": {
                            "user_id": render_msg.user_id,
                            "nickname": render_msg.nickname,
                            "card": render_msg.card,
                            "title": render_msg.title,
                            "role": render_msg.role
                        },
                        "message": mr_msg.get_message_chain_list() or [],
                        "time": render_msg.timestamp,
                        "raw_message": raw,
                        "_source": "message_recorder"
                    }
            except Exception as e:
                logger.warning(f"通过 message_recorder 获取消息失败: message_id={message_id}, 错误: {e}")

        if self.onebot:
            logger.debug("message_recorder 不可用，降级使用 OneBot API")
            try:
                msg_data = await self.onebot.get_msg(message_id)
                if msg_data:
                    msg_data["_source"] = "onebot"
                    return msg_data
            except Exception as e:
                logger.warning(f"通过 OneBot API 获取消息失败: message_id={message_id}, 错误: {e}")

        return None

    async def get_messages_after(
        self,
        reference_message_id: int,
        group_id: int,
        count: int = 10,
        filter_user_id: Optional[int] = None
    ) -> List[dict]:
        """
        获取指定消息之后的消息列表

        Args:
            reference_message_id: 参考消息 ID
            group_id: 群号
            count: 获取数量
            filter_user_id: 过滤指定用户 ID

        Returns:
            消息列表
        """
        mr_api = await self.get_message_recorder_api()

        if mr_api:
            try:
                ref_msg = await mr_api.get_by_id(int(reference_message_id))
                if ref_msg:
                    context = await mr_api.get_context(
                        message_id=ref_msg.id,
                        before=0,
                        after=count * 2
                    )

                    after_messages = context.get("after", [])
                    messages = []

                    for mr_msg in after_messages:
                        if filter_user_id and int(mr_msg.sender_id) != filter_user_id:
                            continue

                        render_msg = await self.convert_mr_to_render(mr_msg, group_id)
                        raw = mr_msg.get_raw_message_dict() or {}

                        messages.append({
                            "message_id": mr_msg.message_id,
                            "group_id": int(mr_msg.group_id) if mr_msg.group_id else None,
                            "sender": {
                                "user_id": render_msg.user_id,
                                "nickname": render_msg.nickname,
                                "card": render_msg.card,
                                "title": render_msg.title,
                                "role": render_msg.role
                            },
                            "message": mr_msg.get_message_chain_list() or [],
                            "time": render_msg.timestamp,
                            "raw_message": raw,
                            "_source": "message_recorder"
                        })

                        if len(messages) >= count:
                            break

                    logger.info(f"通过 message_recorder 获取到 {len(messages)} 条消息")
                    return messages

            except Exception as e:
                logger.warning(f"通过 message_recorder 获取历史消息失败: {e}")

        if self.onebot:
            logger.debug("message_recorder 不可用，降级使用 OneBot API")
            try:
                history = await self.onebot.get_history(group_id, 0, count * 3)
                if history:
                    if isinstance(history, dict):
                        messages_history = history.get("messages", [])
                    elif isinstance(history, list):
                        messages_history = history
                    else:
                        messages_history = []

                    ref_msg_data = await self.onebot.get_msg(reference_message_id)
                    if ref_msg_data:
                        ref_time = ref_msg_data.get("time", 0)

                        newer_messages = [
                            m for m in messages_history
                            if m.get("time", 0) > ref_time
                        ]

                        if filter_user_id:
                            newer_messages = [
                                m for m in newer_messages
                                if m.get("sender", {}).get("user_id") == filter_user_id
                            ]

                        newer_messages.sort(key=lambda x: x.get("time", 0))
                        messages = newer_messages[:count]

                        for msg in messages:
                            msg["_source"] = "onebot"

                        logger.info(f"通过 OneBot API 获取到 {len(messages)} 条消息")
                        return messages

            except Exception as e:
                logger.warning(f"通过 OneBot API 获取历史消息失败: {e}")

        return []

    async def get_messages_for_quote(
        self,
        reply_id: int,
        group_id: Optional[int],
        count: int = 1,
        filter_user_id: Optional[int] = None,
        pick_indices: Optional[List[int]] = None
    ) -> tuple:
        """
        获取用于语录渲染的消息列表

        Args:
            reply_id: 被回复消息 ID
            group_id: 群号
            count: 获取数量
            filter_user_id: 过滤指定用户 ID
            pick_indices: 精选消息序号列表

        Returns:
            (消息列表, 错误信息)
        """
        reply_msg = await self.get_message_by_id(reply_id, group_id)

        if not reply_msg:
            return [], "无法获取消息内容，请确认消息是否存在"

        if filter_user_id is True:
            sender = reply_msg.get("sender", {})
            filter_user_id = sender.get("user_id")
            if not filter_user_id:
                return [], "无法获取被回复消息的发送者信息"
            logger.debug(f"--user 未指定QQ号，自动使用被回复消息发送者: {filter_user_id}")

        messages_data = [reply_msg]

        need_more = count > 1 or (pick_indices and max(pick_indices) > 1)
        if pick_indices:
            count = len(pick_indices)

        if need_more and group_id:
            fetch_count = 100 if pick_indices else (count * 5 if filter_user_id else count)
            fetch_count = min(fetch_count, 100)

            newer_messages = await self.get_messages_after(
                reply_id, group_id, fetch_count, filter_user_id
            )

            if pick_indices:
                need_count = max(pick_indices) - 1
                if len(newer_messages) > need_count:
                    newer_messages = newer_messages[:need_count]

            messages_data.extend(newer_messages)

        if pick_indices:
            max_idx = max(pick_indices)
            if max_idx > len(messages_data):
                return [], f"指定的消息序号 {max_idx} 超出范围，当前最多可获取 {len(messages_data)} 条消息"

            picked_messages = []
            for idx in pick_indices:
                if 1 <= idx <= len(messages_data):
                    picked_messages.append(messages_data[idx - 1])
            messages_data = picked_messages

            if not messages_data:
                return [], "未找到指定的消息"

        if filter_user_id and not pick_indices:
            messages_data = [
                m for m in messages_data
                if m.get("sender", {}).get("user_id") == filter_user_id
            ]
            if count > 1 and len(messages_data) > count:
                messages_data = messages_data[-count:]

            if not messages_data:
                return [], f"未找到该用户（QQ: {filter_user_id}）的消息"

        return messages_data, None

    def reset(self):
        """重置状态（用于重新检测 message_recorder）"""
        self._mr_checked = False
        self._mr_api = None
