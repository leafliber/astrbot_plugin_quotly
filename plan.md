# AstrBot Quotlin Plugin 计划

## 项目概述

复刻 [quote-bot](https://github.com/LyoSU/quote-bot) 项目，将其迁移到 QQ 平台。作为 AstrBot 的插件，通过 OneBot11 协议获取历史消息，并使用 CairoSVG 渲染成精美的引用图片。

## 功能需求

1. **回复引用消息生成图片**：用户通过回复消息触发，解析 `reply` 消息段获取原消息 ID
2. **通过 OneBot11 `get_msg` API**：根据消息 ID 获取消息详情（发送者、昵称、头像、时间、内容）
3. **SVG 渲染**：使用 CairoSVG 将消息渲染为精美的 PNG/WebP 图片
4. **多消息合并渲染**：支持通过指令参数指定连续消息范围
5. **群消息支持**：主要支持 QQ 群消息，预留私聊消息支持

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 插件框架 | AstrBot Star 类 |
| 消息协议 | OneBot11 |
| SVG 渲染 | CairoSVG + Pillow |
| 异步 HTTP | aiohttp |
| 数据存储 | 插件 data 目录 |

## 插件结构

```
astrbot_plugin_quotly/
├── main.py                      # 插件主入口
├── metadata.yaml                # 插件元数据
├── requirements.txt             # Python 依赖
├── _conf_schema.json            # 配置文件 Schema
├── assets/
│   └── fonts/                   # 字体文件（思源黑体/等宽字体）
├── core/
│   ├── __init__.py
│   ├── message_parser.py        # 消息解析（reply 消息段）
│   ├── quotly_renderer.py       # SVG 渲染器（核心）
│   └── onebot_client.py         # OneBot11 API 客户端
└── utils/
    ├── __init__.py
    └── text_utils.py            # 文本处理工具
```

## 核心模块设计

### 1. OneBot11 API 客户端 (`onebot_client.py`)

通过 astrbot 的 context 调用 OneBot11 API：

```python
# 通过 get_msg 获取单条消息
async def get_msg(self, message_id: int) -> dict:
    result = await self.context.request("get_msg", {"message_id": message_id})
    return result

# 通过 get_history 获取消息历史（如果有扩展支持）
async def get_history(self, group_id: int, start_message_id: int = 0, count: int = 20) -> list:
    result = await self.context.request("get_history", {
        "group_id": group_id,
        "start_message_id": start_message_id,
        "count": count
    })
    return result
```

### 2. 消息解析器 (`message_parser.py`)

解析事件中的 reply 消息段：

```python
def parse_reply(self, event) -> Optional[int]:
    """从事件中解析被回复的消息 ID"""
    for segment in event.message_obj:
        if segment.type == "reply":
            return int(segment.data.get("id"))
    return None
```

### 3. SVG 渲染器 (`quotly_renderer.py`)

核心渲染逻辑：

- **输入**：消息对象列表（sender, nickname, avatar, time, text）
- **SVG 模板**：参考 quote-bot 设计，支持气泡样式
- **头像**：圆形裁剪
- **时间戳**：格式化显示
- **输出**：PNG 格式字节流

```python
class QuotlyRenderer:
    def __init__(self, font_path: str):
        self.font_path = font_path
        self.avatar_size = 50
        self.bubble_padding = 15

    def render(self, messages: list[dict]) -> bytes:
        """渲染消息列表为图片"""
        svg = self._build_svg(messages)
        return cairosvg.svg2png(bytestring=svg)

    def _build_svg(self, messages: list[dict]) -> str:
        """构建 SVG 字符串"""
        # 动态计算高度
        # 头像 + 昵称 + 时间 + 消息内容
```

## 指令设计

| 指令 | 说明 |
|------|------|
| `/quote [数量]` | 回复某条消息并发送指令，生成该消息的引用图片 |
| `/quote range [起始ID] [结束ID]` | 渲染指定范围的多条连续消息 |

## 工作流程

1. **接收事件**：用户发送消息，插件接收 `AstrMessageEvent`
2. **解析回复**：检查消息中是否包含 `reply` 消息段
3. **获取消息详情**：调用 `get_msg` API 获取被回复消息的完整内容
4. **构建数据**：解析 sender、nickname、avatar_url、time、text
5. **渲染图片**：调用 QuotlyRenderer 生成 PNG
6. **发送结果**：通过 `yield event.image_result()` 返回图片

## 消息格式

OneBot11 `get_msg` 返回格式：

```json
{
  "time": 1704067200,
  "message_type": "group",
  "message_id": 123456,
  "real_id": 123456,
  "sender": {
    "user_id": 10001,
    "nickname": "用户名",
    "card": "群名片"
  },
  "message": [
    {"type": "text", "data": {"text": "消息内容"}}
  ]
}
```

## 头像获取方案

**已确认**：OneBot11 **没有** `get_user_info` API，但有 `get_stranger_info(user_id)` 可获取陌生人信息。

**QQ 头像直接获取**（无需 API）：
```
https://q.qlogo.cn/headimg_dl?dst_uin={qq号}&spec=640
```
- `spec=100` = 100x100 小图
- `spec=640` = 640x640 高清图

## 待确认问题

1. **get_msg API 可用性**：需要确认 AstrBot 的 OneBot11 适配器是否支持 `get_msg` API
2. **历史消息 API**：如果 `get_history` 不可用，需要寻找替代方案

## 实现步骤

1. 创建项目结构和基础文件
2. 实现 `onebot_client.py` - API 调用层
3. 实现 `message_parser.py` - 消息解析
4. 实现 `quotly_renderer.py` - SVG 渲染核心
5. 实现 `main.py` - 插件主逻辑和指令
6. 编写 `metadata.yaml` 和配置文件
7. 测试和调试
