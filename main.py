"""
AstrBot Quotly Plugin
复刻 quote-bot 项目，将 QQ 消息渲染为精美的引用图片
"""

import asyncio
import os
import random
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
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp

from core.onebot_client import OneBotClient
from core.message_parser import MessageParser
from core.quotly_renderer import QuotlyRenderer
from core.database import QuotlyDatabase
from core.message_provider import MessageProvider
from utils.image_hash import compute_phash


@register("quotly", "Leafiber", "将消息渲染为精美的引用图片", "1.0.0")
class QuotlyPlugin(Star):
    """引用消息渲染插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.parser = MessageParser()
        self.onebot = OneBotClient()

        self.renderer = QuotlyRenderer()

        plugin_name = getattr(self, 'name', 'quotly')
        self.db = QuotlyDatabase(plugin_name=plugin_name)

        self.message_provider = MessageProvider(context, self.onebot, self.parser)

        self.q_trigger = ""
        self.qsearch_trigger = ""
        self.qrandom_trigger = ""
        self._load_config()

        self._font_init_task = asyncio.create_task(self._init_fonts())

        logger.info("Quotly 插件已加载")

    async def _init_fonts(self):
        """初始化字体文件（后台任务）"""
        try:
            await self.renderer.ensure_fonts()
        except Exception as e:
            logger.warning(f"字体初始化失败: {e}")

    def _load_config(self):
        trigger_words = self.config.get("trigger_words", {})
        self.q_trigger = trigger_words.get("q_trigger", "").strip()
        self.qsearch_trigger = trigger_words.get("qsearch_trigger", "").strip()
        self.qrandom_trigger = trigger_words.get("qrandom_trigger", "").strip()
        logger.info(f"触发词配置: q={self.q_trigger or '未设置'}, qsearch={self.qsearch_trigger or '未设置'}, qrandom={self.qrandom_trigger or '未设置'}")

        render_options = self.config.get("render_options", {})
        self.show_title = render_options.get("show_title", True)
        self.show_time = render_options.get("show_time", True)
        self.show_date = render_options.get("show_date", True)
        logger.info(f"渲染选项: show_title={self.show_title}, show_time={self.show_time}, show_date={self.show_date}")

        ocr_options = self.config.get("ocr_options", {})
        self.enable_ocr = ocr_options.get("enable_ocr", False)
        logger.info(f"OCR选项: enable_ocr={self.enable_ocr}")

        permission_options = self.config.get("permission_options", {})
        self.qdel_require_admin = permission_options.get("qdel_require_admin", True)
        logger.info(f"权限选项: qdel_require_admin={self.qdel_require_admin}")

    def _extract_image_urls(self, message) -> list:
        """
        从消息中提取所有图片URL
        
        Args:
            message: OneBot11 message 数组
            
        Returns:
            图片URL列表
        """
        image_urls = []
        if not message or not isinstance(message, (list, tuple)):
            return image_urls
            
        for segment in message:
            if isinstance(segment, dict):
                seg_type = segment.get("type")
                seg_data = segment.get("data", {})
                if seg_type == "image":
                    url = seg_data.get("url", "") or seg_data.get("file", "")
                    if url:
                        image_urls.append(url)
                elif seg_type == "mface":
                    url = seg_data.get("url", "")
                    if url:
                        image_urls.append(url)
        
        return image_urls

    def _truncate_base64_in_message(self, message: list, max_len: int = 50) -> list:
        """
        截断消息中的 base64 数据，用于日志输出
        
        Args:
            message: 消息列表
            max_len: base64 数据最大显示长度
            
        Returns:
            处理后的消息列表（仅用于日志）
        """
        import copy
        result = copy.deepcopy(message)
        for seg in result:
            if isinstance(seg, dict) and "data" in seg:
                data = seg["data"]
                if isinstance(data, dict):
                    for key in ["url", "file"]:
                        if key in data and isinstance(data[key], str):
                            val = data[key]
                            if val.startswith("data:") and len(val) > max_len:
                                data[key] = val[:max_len] + f"...(共{len(val)}字符)"
        return result

    async def _ocr_image(self, image_url: str) -> str:
        """
        使用AstrBot的视觉模型对图片进行OCR识别
        
        Args:
            image_url: 图片URL
            
        Returns:
            OCR识别结果文本
        """
        try:
            result = await self.context.llm.chat(
                prompt="请识别这张图片中的所有文字内容，只输出识别到的文字，不要添加任何解释或说明。如果图片中没有文字，请输出：[无文字]",
                image_urls=[image_url]
            )
            
            if result:
                ocr_text = result.strip()
                if ocr_text and ocr_text != "[无文字]":
                    logger.debug(f"OCR识别成功: {ocr_text[:100]}...")
                    return ocr_text
            
            return ""
            
        except Exception as e:
            logger.warning(f"OCR识别失败: {e}")
            return ""

    async def _download_and_hash_image(self, image_url: str) -> str:
        """
        下载图片并计算hash

        Args:
            image_url: 图片URL

        Returns:
            图片hash值，失败返回空字符串
        """
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        image_hash = compute_phash(image_data)
                        if image_hash:
                            logger.debug(f"图片hash计算成功: {image_hash}")
                            return image_hash
                        else:
                            logger.warning("图片hash计算失败")
                    else:
                        logger.warning(f"下载图片失败: HTTP {resp.status}")
            
            return ""
            
        except Exception as e:
            logger.warning(f"下载图片失败: {e}")
            return ""

    async def _background_ocr_update(self, image_hash: str, ocr_tasks_data: list, storage_messages: list):
        """
        后台执行 OCR 并更新数据库记录
        
        Args:
            image_hash: 图片 hash 值
            ocr_tasks_data: OCR 任务数据列表，每项为 (消息索引, 图片URL列表)
            storage_messages: 存储的消息列表
        """
        try:
            for msg_idx, image_urls in ocr_tasks_data:
                ocr_results = []
                for img_url in image_urls:
                    try:
                        ocr_result = await self._ocr_image(img_url)
                        if ocr_result:
                            ocr_results.append(ocr_result)
                    except Exception as e:
                        logger.debug(f"OCR 失败: {e}")
                
                if ocr_results:
                    ocr_text = " ".join(ocr_results)
                    storage_messages[msg_idx]["ocr_text"] = ocr_text
                    logger.debug(f"消息 {msg_idx} 后台 OCR 完成: {ocr_text[:100]}...")
            
            try:
                await self.db.update_ocr_text(image_hash, storage_messages)
                logger.debug(f"OCR 结果已更新到数据库: hash={image_hash}")
            except Exception as e:
                logger.warning(f"更新 OCR 结果失败: {e}")
                
        except Exception as e:
            logger.warning(f"后台 OCR 任务失败: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """
        监听所有平台消息，处理自定义触发词
        """
        message_str = event.message_str.strip()
        
        if self.q_trigger and message_str.startswith(self.q_trigger):
            args = message_str[len(self.q_trigger):].strip()
            async for result in self._handle_quote(event, args):
                yield result
            return
        
        if self.qsearch_trigger and message_str.startswith(self.qsearch_trigger):
            args = message_str[len(self.qsearch_trigger):].strip()
            async for result in self._handle_search(event, args):
                yield result
            return
        
        if self.qrandom_trigger and message_str == self.qrandom_trigger:
            await self._handle_random(event, "")
            return

    @filter.command("q")
    async def quote_command(self, event: AstrMessageEvent):
        """
        将消息渲染为精美的引用图片
        用法: /q [数量] [silent] [--title 0|1] [--time 0|1] [--date 0|1] [--user [QQ号]] [--pick 序号列表]
        silent: 静默模式，只保存语录不发送图片，仅返回保存结果
        """
        message_str = event.message_str.strip()
        args = re.sub(r'^q\s*', '', message_str)
        async for result in self._handle_quote(event, args):
            yield result

    async def _handle_quote(self, event: AstrMessageEvent, args: str):
        self.onebot.set_event(event)

        reply_id = self.parser.parse_reply(event)

        if reply_id is None:
            yield event.plain_result("请先回复一条消息，再使用 /q 指令")
            return

        count = 1
        show_title = self.show_title
        show_time = self.show_time
        show_date = self.show_date
        silent = False
        
        logger.debug(f"解析消息: args='{args}'")

        silent_match = re.search(r'\bsilent\b', args, re.IGNORECASE)
        if silent_match:
            silent = True
            args = args[:silent_match.start()] + args[silent_match.end():]

        match = re.match(r'^(\d+)', args)
        if match:
            count = int(match.group(1))
            if count < 1:
                count = 1
            if count > 100:
                count = 100

        title_match = re.search(r'--title\s+([01])', args)
        if title_match:
            show_title = title_match.group(1) == '1'

        time_match = re.search(r'--time\s+([01])', args)
        if time_match:
            show_time = time_match.group(1) == '1'

        date_match = re.search(r'--date\s+([01])', args)
        if date_match:
            show_date = date_match.group(1) == '1'

        filter_user_id = None
        user_match = re.search(r'--user(?:\s+(\d+))?', args)
        if user_match:
            if user_match.group(1):
                filter_user_id = int(user_match.group(1))
            else:
                filter_user_id = True

        pick_indices = None
        pick_match = re.search(r'--pick\s+([0-9,\-\s]+)', args)
        if pick_match:
            pick_str = pick_match.group(1)
            pick_indices = set()
            for part in pick_str.split(','):
                part = part.strip()
                if '-' in part:
                    try:
                        start, end = part.split('-', 1)
                        start, end = int(start.strip()), int(end.strip())
                        pick_indices.update(range(start, end + 1))
                    except ValueError:
                        pass
                else:
                    try:
                        pick_indices.add(int(part))
                    except ValueError:
                        pass
            pick_indices = sorted(pick_indices)

        logger.debug(f"解析结果: count={count}, show_title={show_title}, show_time={show_time}, show_date={show_date}, filter_user_id={filter_user_id}, pick_indices={pick_indices}")

        group_id_str = getattr(event.message_obj, 'group_id', None)
        group_id = None
        if group_id_str:
            try:
                group_id = int(group_id_str)
            except (ValueError, TypeError):
                pass

        messages_data, error_msg = await self.message_provider.get_messages_for_quote(
            reply_id=reply_id,
            group_id=group_id,
            count=count,
            filter_user_id=filter_user_id,
            pick_indices=pick_indices
        )

        if error_msg:
            yield event.plain_result(error_msg)
            return

        if not messages_data:
            yield event.plain_result("无法获取消息内容，请确认消息是否存在")
            return

        source = messages_data[0].get("_source", "unknown")
        logger.info(f"消息获取来源: {source}, 消息数量: {len(messages_data)}")

        if group_id is None and messages_data:
            first_msg = messages_data[0]
            gid = first_msg.get("group_id")
            if gid:
                group_id = int(gid) if isinstance(gid, str) else gid

        # 渲染消息列表
        try:
            render_messages = []
            last_date = None
            
            for msg_data_item in messages_data:
                msg_time = msg_data_item.get("time", 0)
                
                if show_date:
                    from datetime import datetime
                    try:
                        msg_datetime = datetime.fromtimestamp(msg_time)
                        msg_date = msg_datetime.date()
                        date_str = msg_datetime.strftime("%Y年%m月%d日")
                        
                        if last_date is None or msg_date != last_date:
                            render_messages.append({
                                "type": "date_separator",
                                "date_str": date_str
                            })
                            last_date = msg_date
                    except (ValueError, OSError):
                        pass
                
                sender = msg_data_item.get("sender", {})
                
                if isinstance(sender, dict) and "card" in sender and "title" in sender and "role" in sender:
                    user_id = sender.get("user_id", 0)
                    nickname = sender.get("nickname", "")
                    card = sender.get("card", "")
                    title = sender.get("title", "")
                    role = sender.get("role", "member")
                    logger.debug(f"使用 sender 中的完整信息: card={card}, title={title}, role={role}")
                else:
                    user_id, nickname, card, title, role = self.parser.parse_sender_info(sender)
                
                msg_content = msg_data_item.get("message", [])
                log_content = self._truncate_base64_in_message(msg_content)
                logger.debug(f"解析消息内容: message 类型={type(msg_content)}, 内容={log_content}")
                
                parse_result = self.parser.parse_message_content(msg_content)
                logger.debug(f"parse_message_content 返回值: 类型={type(parse_result)}, 值={parse_result}")
                
                if not isinstance(parse_result, tuple) or len(parse_result) != 2:
                    logger.error(f"parse_message_content 返回值异常: {parse_result}")
                    content = str(msg_content) if msg_content else "[空消息]"
                    inner_reply_id = None
                else:
                    content, inner_reply_id = parse_result
                    
                time_str = self.parser.format_time_short(msg_time)

                if not content:
                    content = "[仅包含媒体消息]"

                if not title and group_id and user_id and self.onebot:
                    try:
                        member_info = await self.onebot.get_group_member_info(group_id, user_id)
                        if member_info:
                            title = member_info.get("title", "")
                            if not card:
                                card = member_info.get("card", "")
                            if role == "member":
                                role = member_info.get("role", "member")
                    except Exception as e:
                        logger.debug(f"获取群成员信息失败: {e}")

                reply_info = None
                if inner_reply_id:
                    try:
                        reply_msg_data = await self.message_provider.get_message_by_id(inner_reply_id, group_id)
                        if reply_msg_data:
                            reply_sender = reply_msg_data.get("sender", {})
                            if isinstance(reply_sender, dict) and "card" in reply_sender:
                                reply_nickname = reply_sender.get("nickname", "")
                                reply_card = reply_sender.get("card", "")
                            else:
                                _, reply_nickname, reply_card, _, _ = self.parser.parse_sender_info(reply_sender)
                            
                            reply_content, _ = self.parser.parse_message_content(
                                reply_msg_data.get("message", [])
                            )
                            
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
                    "avatar_url": self.message_provider._get_avatar_url(user_id),
                    "reply_info": reply_info
                })

            png_data = await self.renderer.arender(
                render_messages, 
                show_title=show_title, 
                show_time=show_time,
                show_date=show_date
            )

            image_hash = compute_phash(png_data) or "unknown"

            duplicate_records = await self.db.find_by_hash(image_hash, threshold=5)
            if duplicate_records:
                duplicate = duplicate_records[0]
                distance = duplicate.get('hamming_distance', 0)
                logger.info(f"检测到相似语录: hash={duplicate.get('image_hash')}, 汉明距离={distance}")
                
                duplicate_path = duplicate.get('image_path')
                if duplicate_path and Path(duplicate_path).exists():
                    logger.debug(f"返回已存在的相似语录: {duplicate_path}")
                    if silent:
                        await self.context.send_message(
                            event.unified_msg_origin,
                            [Comp.Plain(f"语录已存在（相似度: {100 - distance * 3}%），未保存新记录")]
                        )
                        return
                    else:
                        await asyncio.sleep(random.uniform(0, 2))
                        yield event.chain_result([
                            Comp.Image.fromFileSystem(duplicate_path),
                            Comp.Plain(f"\n检测到相似语录（相似度: {100 - distance * 3}%），已返回已有记录")
                        ])
                    return

            storage_messages = []
            ocr_tasks_data = []
            
            for i, msg_data_item in enumerate(messages_data):
                sender = msg_data_item.get("sender", {})
                
                if isinstance(sender, dict) and "card" in sender and "title" in sender and "role" in sender:
                    user_id = sender.get("user_id", 0)
                    nickname = sender.get("nickname", "")
                    card = sender.get("card", "")
                    title = sender.get("title", "")
                    role = sender.get("role", "member")
                else:
                    user_id, nickname, card, title, role = self.parser.parse_sender_info(sender)
                
                content, _ = self.parser.parse_message_content(msg_data_item.get("message", []))
                time_str = self.parser.format_time_short(msg_data_item.get("time", 0))
                original_time = msg_data_item.get("time", 0)

                storage_messages.append({
                    "user_id": user_id,
                    "nickname": nickname,
                    "card": card,
                    "title": title,
                    "role": role,
                    "content": content,
                    "ocr_text": "",
                    "time_str": time_str,
                    "original_time": original_time
                })
                
                if self.enable_ocr:
                    image_urls = self._extract_image_urls(msg_data_item.get("message", []))
                    if image_urls:
                        ocr_tasks_data.append((i, image_urls))

            try:
                await self.db.save_record(image_hash, png_data, group_id, storage_messages)
                logger.debug(f"Quotly 记录已保存: hash={image_hash}")
            except Exception as e:
                logger.warning(f"保存 Quotly 记录失败: {e}")

            if ocr_tasks_data:
                asyncio.create_task(self._background_ocr_update(image_hash, ocr_tasks_data, storage_messages))

            if silent:
                await self.context.send_message(
                    event.unified_msg_origin,
                    [Comp.Plain(f"语录保存成功（{len(storage_messages)} 条消息）")]
                )
                return
            else:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    f.write(png_data)
                    temp_path = f.name

                try:
                    await asyncio.sleep(random.uniform(0, 2))
                    yield event.chain_result([Comp.Image.fromFileSystem(temp_path)])
                finally:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)

        except Exception as e:
            import traceback
            logger.error(f"渲染失败: {e}")
            logger.debug(f"错误堆栈:\n{traceback.format_exc()}")
            yield event.plain_result(f"渲染失败: {str(e)}")

    @filter.command("qsearch")
    async def search_command(self, event: AstrMessageEvent):
        """
        搜索已保存的语录记录
        用法: /qsearch <关键词> [-u <QQ号>] [-g <群号>] [-a] [-n <数量>]
        默认返回 1 张图片，可通过 -n 参数指定最大返回数量（1-5）
        """
        message_str = event.message_str.strip()
        args = re.sub(r'^qsearch\s*', '', message_str)
        async for result in self._handle_search(event, args):
            yield result

    async def _handle_search(self, event: AstrMessageEvent, args: str):
        if not args:
            yield event.plain_result("用法: /qsearch <关键词>\n选项: -u <QQ号>, -g <群号>, -a (全局搜索), -n <数量> (默认1，最大5)")
            return

        group_id_str = getattr(event.message_obj, 'group_id', None)
        current_group_id = None
        if group_id_str:
            try:
                current_group_id = int(group_id_str)
            except (ValueError, TypeError):
                pass

        group_id = current_group_id
        user_id = None
        max_count = 1
        keyword = args

        if re.search(r'-a\b', args):
            group_id = None
            keyword = re.sub(r'-a\b\s*', '', keyword)

        user_match = re.search(r'-u\s*(\d+)', args)
        if user_match:
            try:
                user_id = int(user_match.group(1))
            except ValueError:
                pass
            keyword = re.sub(r'-u\s*\d+\s*', '', keyword)

        group_match = re.search(r'-g\s*(\d+)', args)
        if group_match:
            try:
                group_id = int(group_match.group(1))
            except ValueError:
                pass
            keyword = re.sub(r'-g\s*\d+\s*', '', keyword)

        num_match = re.search(r'-n\s*(\d+)', args)
        if num_match:
            try:
                max_count = int(num_match.group(1))
                if max_count < 1:
                    max_count = 1
                elif max_count > 5:
                    max_count = 5
            except ValueError:
                pass
            keyword = re.sub(r'-n\s*\d+\s*', '', keyword)

        keyword = keyword.strip()

        try:
            search_limit = 20
            if user_id:
                results = await self.db.search_by_user(user_id, group_id, limit=search_limit)
            elif keyword:
                results = await self.db.search_by_keyword(keyword, group_id, limit=search_limit)
            else:
                yield event.plain_result("请提供搜索关键词或使用 -u 指定用户")
                return

            if not results:
                search_scope = "所有群" if group_id is None else f"本群"
                yield event.plain_result(f"未在{search_scope}找到匹配的 Quotly 记录")
                return

            random.shuffle(results)
            selected_results = results[:max_count]

            for result in selected_results:
                image_path = result.get('image_path')
                if image_path and Path(image_path).exists():
                    await asyncio.sleep(random.uniform(0, 2))
                    yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
                else:
                    yield event.plain_result(f"图片文件不存在: {image_path}")

            if len(results) > max_count:
                yield event.plain_result(f"共找到 {len(results)} 条记录，随机显示 {max_count} 条")

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            yield event.plain_result(f"搜索失败: {str(e)}")

    @filter.command("qrandom")
    async def random_command(self, event: AstrMessageEvent):
        """
        随机获取一条语录记录
        用法: /qrandom [-g <群号>] [-a]
        """
        message_str = event.message_str.strip()
        args = re.sub(r'^qrandom\s*', '', message_str)
        await self._handle_random(event, args)

    async def _handle_random(self, event: AstrMessageEvent, args: str):
        group_id_str = getattr(event.message_obj, 'group_id', None)
        current_group_id = None
        if group_id_str:
            try:
                current_group_id = int(group_id_str)
            except (ValueError, TypeError):
                pass

        group_id = current_group_id

        if re.search(r'-a\b', args):
            group_id = None

        group_match = re.search(r'-g\s*(\d+)', args)
        if group_match:
            try:
                group_id = int(group_match.group(1))
            except ValueError:
                pass

        try:
            results = await self.db.get_random(group_id, limit=1)

            if not results:
                search_scope = "所有群" if group_id is None else "本群"
                await self.context.send_message(
                    event.unified_msg_origin,
                    [Comp.Plain(f"暂无{search_scope} Quotly 记录")]
                )
                return

            result = results[0]
            image_path = result.get('image_path')
            if image_path and Path(image_path).exists():
                await asyncio.sleep(random.uniform(0, 2))
                await self.context.send_message(
                    event.unified_msg_origin,
                    [Comp.Image.fromFileSystem(image_path)]
                )
            else:
                await self.context.send_message(
                    event.unified_msg_origin,
                    [Comp.Plain(f"图片文件不存在: {image_path}")]
                )

        except Exception as e:
            logger.error(f"随机获取失败: {e}")
            await self.context.send_message(
                event.unified_msg_origin,
                [Comp.Plain(f"随机获取失败: {str(e)}")]
            )

    @filter.command("qstats")
    async def stats_command(self, event: AstrMessageEvent):
        """
        查看语录统计信息
        用法: /qstats
        """
        try:
            stats = await self.db.get_stats()
            yield event.plain_result(
                f"Quotly 统计:\n"
                f"总记录数: {stats['total_records']}\n"
                f"总消息数: {stats['total_messages']}\n"
                f"群组数: {stats['total_groups']}"
            )
        except Exception as e:
            logger.error(f"获取统计失败: {e}")
            yield event.plain_result(f"获取统计失败: {str(e)}")

    @filter.command("qdel")
    async def delete_command(self, event: AstrMessageEvent):
        """
        删除语录记录
        用法: /qdel（需回复机器人发送的语录图片）
        """
        if self.qdel_require_admin:
            is_authorized = False
            
            if hasattr(event, 'role') and event.role == 'admin':
                is_authorized = True
            
            if not is_authorized:
                group_id = getattr(event.message_obj, 'group_id', None)
                if group_id:
                    user_id = getattr(event.message_obj, 'sender', None)
                    if user_id:
                        user_id = getattr(user_id, 'user_id', None)
                    
                    if user_id:
                        try:
                            member_info = await self.onebot.get_group_member_info(int(group_id), int(user_id))
                            if member_info:
                                role = member_info.get('role', 'member')
                                if role in ['owner', 'admin']:
                                    is_authorized = True
                        except Exception as e:
                            logger.warning(f"检查用户权限失败: {e}")
            
            if not is_authorized:
                yield event.plain_result("删除语录需要群管理员或AstrBot管理员权限")
                return
        
        async for result in self._handle_delete(event):
            yield result

    async def _handle_delete(self, event: AstrMessageEvent):
        self.onebot.set_event(event)

        reply_id = self.parser.parse_reply(event)

        if reply_id is None:
            yield event.plain_result("请先回复一条语录图片消息，再使用 /qdel 指令")
            return

        try:
            msg_data = await self.message_provider.get_message_by_id(reply_id)

            if msg_data is None:
                yield event.plain_result("无法获取消息内容，请确认消息是否存在")
                return

            message = msg_data.get("message", [])
            image_urls = self._extract_image_urls(message)

            if not image_urls:
                yield event.plain_result("被回复的消息中没有图片，请回复语录图片消息")
                return

            deleted_count = 0
            for image_url in image_urls:
                image_hash = await self._download_and_hash_image(image_url)
                
                if not image_hash:
                    logger.warning(f"无法计算图片hash: {image_url}")
                    continue

                matches = await self.db.find_by_hash(image_hash, threshold=5)

                for match in matches:
                    record_id = match.get('id')
                    if await self.db.delete_by_id(record_id):
                        deleted_count += 1
                        logger.info(f"已删除语录: record_id={record_id}, hash={image_hash}")

            if deleted_count > 0:
                yield event.plain_result(f"已成功删除 {deleted_count} 条语录记录")
            else:
                yield event.plain_result("未找到匹配的语录记录")

        except Exception as e:
            import traceback
            logger.error(f"删除语录失败: {e}")
            logger.debug(f"错误堆栈:\n{traceback.format_exc()}")
            yield event.plain_result(f"删除失败: {str(e)}")

    @filter.llm_tool(name="qsearch")
    async def qsearch_tool(self, event: AstrMessageEvent, keyword: str, user_id: str = "", group_id: str = "", global_search: str = "false") -> MessageEventResult:
        '''搜索语录记录。根据关键词搜索已保存的语录图片，支持按用户或群组筛选。

        Args:
            keyword(string): 搜索关键词，用于匹配语录内容、发送者昵称等
            user_id(string): 可选，指定发送者的QQ号进行筛选
            group_id(string): 可选，指定群号进行筛选
            global_search(string): 可选，是否全局搜索（跨群），值为 "true" 或 "false"，默认 "false"
        '''
        try:
            search_group_id = None
            search_user_id = None
            
            if global_search.lower() != "true":
                current_group_id_str = getattr(event.message_obj, 'group_id', None)
                if current_group_id_str:
                    try:
                        search_group_id = int(current_group_id_str)
                    except (ValueError, TypeError):
                        pass
            
            if group_id.strip():
                try:
                    search_group_id = int(group_id.strip())
                except ValueError:
                    pass
            
            if user_id.strip():
                try:
                    search_user_id = int(user_id.strip())
                except ValueError:
                    pass

            keyword = keyword.strip()
            
            if search_user_id:
                results = await self.db.search_by_user(search_user_id, search_group_id, limit=5)
            elif keyword:
                results = await self.db.search_by_keyword(keyword, search_group_id, limit=5)
            else:
                yield event.plain_result("请提供搜索关键词")
                return

            if not results:
                search_scope = "所有群" if search_group_id is None else "本群"
                yield event.plain_result(f"未在{search_scope}找到匹配的语录记录")
                return

            result = results[0]
            image_path = result.get('image_path')
            if image_path and Path(image_path).exists():
                messages = result.get('messages', [])
                content_preview = ""
                if messages:
                    contents = [m.get('content', '') for m in messages[:3]]
                    content_preview = " | ".join([c[:50] for c in contents if c])

                yield event.chain_result([
                    Comp.Image.fromFileSystem(image_path),
                    Comp.Plain(f"\n找到 {len(results)} 条记录，显示第1条。{content_preview}")
                ])
            else:
                yield event.plain_result(f"图片文件不存在")

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            yield event.plain_result(f"搜索失败: {str(e)}")

    @filter.llm_tool(name="qrandom")
    async def qrandom_tool(self, event: AstrMessageEvent, group_id: str = "", global_random: str = "false") -> MessageEventResult:
        '''随机获取一条语录记录。随机返回一条已保存的语录图片。

        Args:
            group_id(string): 可选，指定群号获取该群的语录
            global_random(string): 可选，是否全局随机（跨群），值为 "true" 或 "false"，默认 "false"
        '''
        try:
            search_group_id = None
            
            if global_random.lower() != "true":
                current_group_id_str = getattr(event.message_obj, 'group_id', None)
                if current_group_id_str:
                    try:
                        search_group_id = int(current_group_id_str)
                    except (ValueError, TypeError):
                        pass
            
            if group_id.strip():
                try:
                    search_group_id = int(group_id.strip())
                except ValueError:
                    pass

            results = await self.db.get_random(search_group_id, limit=1)

            if not results:
                search_scope = "所有群" if search_group_id is None else "本群"
                yield event.plain_result(f"暂无{search_scope}语录记录")
                return

            result = results[0]
            image_path = result.get('image_path')
            if image_path and Path(image_path).exists():
                messages = result.get('messages', [])
                content_preview = ""
                if messages:
                    contents = [m.get('content', '') for m in messages[:3]]
                    content_preview = " | ".join([c[:50] for c in contents if c])

                yield event.chain_result([
                    Comp.Image.fromFileSystem(image_path),
                    Comp.Plain(f"\n{content_preview}" if content_preview else "")
                ])
            else:
                yield event.plain_result(f"图片文件不存在")

        except Exception as e:
            logger.error(f"随机获取失败: {e}")
            yield event.plain_result(f"随机获取失败: {str(e)}")

    async def terminate(self):
        """插件卸载时调用"""
        await self.renderer.cleanup()
        await self.db.close()
        logger.info("Quotly 插件已卸载")
