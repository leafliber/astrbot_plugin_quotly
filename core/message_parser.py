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

        message_segments = None

        if hasattr(event.message_obj, 'message'):
            message_segments = event.message_obj.message

        if not message_segments:
            return None

        for segment in message_segments:
            if isinstance(segment, str):
                continue

            seg_type = None
            if hasattr(segment, '__class__'):
                seg_type = segment.__class__.__name__.lower()
            elif hasattr(segment, 'type'):
                seg_type = getattr(segment, 'type', None)

            if seg_type == 'reply':
                if hasattr(segment, 'id'):
                    msg_id = getattr(segment, 'id', None)
                    if msg_id is not None:
                        try:
                            return int(msg_id)
                        except (ValueError, TypeError):
                            pass

        return None

    def parse_sender_info(self, sender: dict) -> tuple[int, str, str]:
        """
        解析发送者信息

        Args:
            sender: OneBot11 sender 字典

        Returns:
            (user_id, nickname, card)
        """
        user_id = sender.get("user_id", 0)
        nickname = sender.get("nickname", "")
        card = sender.get("card", "")  # 群名片
        return user_id, nickname, card

    def parse_message_content(self, message: list) -> str:
        """
        解析消息内容，提取纯文本

        Args:
            message: OneBot11 message 数组

        Returns:
            纯文本内容
        """
        if not message:
            return ""

        text_parts = []
        for segment in message:
            if isinstance(segment, dict):
                seg_type = segment.get("type")
                seg_data = segment.get("data", {})
                if seg_type == "text":
                    text_parts.append(seg_data.get("text", ""))
                elif seg_type == "image":
                    text_parts.append("[图片]")
                elif seg_type == "record":
                    text_parts.append("[语音]")
                elif seg_type == "video":
                    text_parts.append("[视频]")
                elif seg_type == "at":
                    text_parts.append(f"@{seg_data.get('name', '')}")
                elif seg_type == "reply":
                    text_parts.append("[回复]")
                # 可以继续添加其他类型...
            elif hasattr(segment, 'type'):
                # 可能是消息段对象
                if segment.type == "text":
                    text_parts.append(getattr(segment.data, 'get', lambda x: "")("text"))
                elif segment.type == "image":
                    text_parts.append("[图片]")

        return "".join(text_parts).strip()

    def format_time(self, timestamp: int) -> str:
        """
        格式化时间戳为可读字符串

        Args:
            timestamp: Unix 时间戳

        Returns:
            格式化后的时间字符串，如 "2024-01-01 12:00:00"
        """
        if not timestamp:
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except Exception:
            return ""

    def format_time_short(self, timestamp: int) -> str:
        """
        格式化时间戳为短格式

        Args:
            timestamp: Unix 时间戳

        Returns:
            短格式时间字符串，如 "12:00"
        """
        if not timestamp:
            return ""
        try:
            return time.strftime("%H:%M", time.localtime(timestamp))
        except Exception:
            return ""
