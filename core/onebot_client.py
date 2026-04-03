"""
OneBot11 API 客户端
通过 AstrBot 的 event 对象获取 bot 对象来调用 OneBot API
"""

from typing import Optional, Any


class OneBotClient:
    """OneBot11 API 客户端"""

    def __init__(self):
        self.bot = None

    def set_event(self, event: Any):
        """
        从事件对象中提取 bot 对象

        Args:
            event: AstrMessageEvent 对象
        """
        if hasattr(event, 'message_obj') and event.message_obj:
            raw_message = getattr(event.message_obj, 'raw_message', None)
            if raw_message:
                self.bot = getattr(raw_message, 'bot', None)

    async def get_msg(self, message_id: int) -> Optional[dict]:
        """
        获取消息详情

        Args:
            message_id: 消息 ID

        Returns:
            消息详情字典，包含 time, message_type, message_id, sender, message 等字段
        """
        if not self.bot:
            return None

        try:
            result = await self.bot.call_action('get_msg', message_id=message_id)
            return result
        except Exception as e:
            return None

    async def get_stranger_info(self, user_id: int) -> Optional[dict]:
        """
        获取陌生人信息（包含昵称）

        Args:
            user_id: 用户 QQ 号

        Returns:
            用户信息字典
        """
        if not self.bot:
            return None

        try:
            result = await self.bot.call_action('get_stranger_info', user_id=user_id)
            return result
        except Exception as e:
            return None

    def get_avatar_url(self, qq: int, size: int = 640) -> str:
        """
        获取 QQ 头像 URL

        Args:
            qq: QQ 号
            size: 头像尺寸，默认 640x640

        Returns:
            头像 URL
        """
        return f"https://q.qlogo.cn/headimg_dl?dst_uin={qq}&spec={size}"

    async def get_history(self, group_id: int, start_message_id: int = 0, count: int = 20) -> Optional[list]:
        """
        获取消息历史

        Args:
            group_id: 群号
            start_message_id: 起始消息 ID
            count: 获取数量

        Returns:
            消息列表
        """
        if not self.bot:
            return None

        try:
            result = await self.bot.call_action('get_group_msg_history', group_id=group_id, start_message_id=start_message_id, count=count)
            return result
        except Exception:
            return None

    async def get_group_member_info(self, group_id: int, user_id: int) -> Optional[dict]:
        """
        获取群成员信息（包含头衔）

        Args:
            group_id: 群号
            user_id: QQ 号

        Returns:
            群成员信息字典
        """
        if not self.bot:
            return None

        try:
            result = await self.bot.call_action('get_group_member_info', group_id=group_id, user_id=user_id)
            return result
        except Exception:
            return None
