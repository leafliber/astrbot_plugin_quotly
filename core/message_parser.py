"""
消息解析器
从 AstrMessageEvent 中解析 reply 消息段和消息内容
"""

from typing import Optional, List
from dataclasses import dataclass
import time


@dataclass
class MessageSegment:
    """消息段"""
    type: str
    data: dict


@dataclass
class ParsedMessage:
    """解析后的消息"""
    message_id: int
    sender_id: int
    nickname: str
    card: str  # 群名片
    time: int
    content: str
    raw_message: List[MessageSegment]


class MessageParser:
    """消息解析器"""

    def _get_segment_type(self, segment) -> Optional[str]:
        """
        获取消息段类型

        Args:
            segment: 消息段对象

        Returns:
            消息段类型字符串（小写）
        """
        if not hasattr(segment, 'type'):
            return segment.__class__.__name__.lower() if hasattr(segment, '__class__') else None

        type_attr = segment.type
        # 处理枚举类型（如 AstrBot 的 ComponentType.Reply）
        if hasattr(type_attr, 'name'):
            return type_attr.name.lower()
        if hasattr(type_attr, 'value'):
            return str(type_attr.value).lower()
        if type_attr is not None:
            return str(type_attr).lower()
        return None

    def parse_reply(self, event) -> Optional[int]:
        """
        从事件中解析被回复的消息 ID

        Args:
            event: AstrMessageEvent 对象

        Returns:
            被回复的消息 ID，如果没有则返回 None
        """
        if not hasattr(event, 'message_obj') or not event.message_obj:
            return None

        message_segments = getattr(event.message_obj, 'message', None)
        if not message_segments:
            return None

        for segment in message_segments:
            if isinstance(segment, str):
                continue

            seg_type = self._get_segment_type(segment)
            if seg_type != 'reply':
                continue

            # 尝试获取消息 ID
            msg_id = getattr(segment, 'id', None)
            if msg_id is not None:
                try:
                    return int(msg_id)
                except (ValueError, TypeError):
                    pass

        return None

    def parse_sender_info(self, sender) -> tuple[int, str, str, str, str]:
        """
        解析发送者信息

        Args:
            sender: OneBot11 sender 字典

        Returns:
            (user_id, nickname, card, title, role)
        """
        if not sender or not isinstance(sender, dict):
            return 0, "", "", "", "member"
        return (
            sender.get("user_id", 0),
            sender.get("nickname", ""),
            sender.get("card", ""),
            sender.get("title", ""),
            sender.get("role", "member")
        )

    def parse_message_content(self, message) -> tuple[str, Optional[int]]:
        """
        解析消息内容，提取纯文本和回复信息

        Args:
            message: 消息数组（OneBot11 格式）

        Returns:
            (纯文本内容, 回复消息ID)
        """
        if not message:
            return "", None

        if not isinstance(message, (list, tuple)):
            return message if isinstance(message, str) else str(message), None

        text_parts = []
        reply_id = None

        for segment in message:
            if isinstance(segment, dict):
                self._parse_onebot_segment(segment, text_parts)
                if segment.get("type") == "reply":
                    rid = segment.get("data", {}).get("id")
                    from astrbot.api import logger
                    logger.debug(f"解析 reply 消息段: segment={segment}, rid={rid}")
                    if rid is not None:
                        try:
                            reply_id = int(rid)
                        except (ValueError, TypeError):
                            pass
            elif hasattr(segment, 'type'):
                self._parse_obj_segment(segment, text_parts)
                seg_type = self._get_segment_type(segment)
                if seg_type == 'reply':
                    rid = getattr(segment, 'id', None)
                    if rid is not None:
                        try:
                            reply_id = int(rid)
                        except (ValueError, TypeError):
                            pass

        return "".join(text_parts).strip(), reply_id

    def _parse_onebot_segment(self, segment: dict, text_parts: list):
        """解析 OneBot11 格式消息段"""
        seg_type = segment.get("type")
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

    def _parse_obj_segment(self, segment, text_parts: list):
        """解析对象形式的消息段"""
        seg_type = self._get_segment_type(segment)

        if seg_type == "text":
            data = getattr(segment, 'data', {})
            text_parts.append(data.get("text", "") if isinstance(data, dict) else "")
        elif seg_type == "image":
            data = getattr(segment, 'data', {})
            if isinstance(data, dict):
                url = data.get("url", "") or data.get("file", "")
                text_parts.append(f"[图片]({url})" if url else "[图片]")
            else:
                text_parts.append("[图片]")

    def format_time(self, timestamp: int) -> str:
        """格式化时间戳为可读字符串"""
        if not timestamp:
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except Exception:
            return ""

    def format_time_short(self, timestamp: int) -> str:
        """格式化时间戳为短格式"""
        if not timestamp:
            return ""
        try:
            return time.strftime("%H:%M", time.localtime(timestamp))
        except Exception:
            return ""