"""
OneBot11 API 客户端
通过 AstrBot 的 context 调用 OneBot11 API
"""

from typing import Optional, Any


class OneBotClient:
    """OneBot11 API 客户端"""

    def __init__(self, context: Any):
        self.context = context

    async def get_msg(self, message_id: int) -> Optional[dict]:
        """
        获取消息详情

        Args:
            message_id: 消息 ID

        Returns:
            消息详情字典，包含 time, message_type, message_id, sender, message 等字段
        """
        try:
            result = await self.context.request("get_msg", {"message_id": message_id})
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
        try:
            result = await self.context.request("get_stranger_info", {"user_id": user_id})
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
