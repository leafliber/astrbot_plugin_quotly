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
from astrbot.api import logger, AstrBotConfig
import astrbot.api.message_components as Comp

from core.onebot_client import OneBotClient
from core.message_parser import MessageParser
from core.quotly_renderer import QuotlyRenderer
from core.database import QuotlyDatabase
from utils.image_hash import compute_phash


@register("quotly", "Leafiber", "将消息渲染为精美的引用图片", "1.0.0")
class QuotlinPlugin(Star):
    """引用消息渲染插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.parser = MessageParser()
        self.onebot = OneBotClient()

        font_dir = Path(__file__).parent / "assets" / "fonts"
        self.renderer = QuotlyRenderer(str(font_dir))

        plugin_name = getattr(self, 'name', 'quotly')
        self.db = QuotlyDatabase(plugin_name=plugin_name)

        self.q_trigger = ""
        self.qsearch_trigger = ""
        self.qrandom_trigger = ""
        self._load_config()

        logger.info("Quotlin 插件已加载")

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

    async def _ocr_image(self, image_url: str) -> str:
        """
        使用AstrBot的视觉模型对图片进行OCR识别
        
        Args:
            image_url: 图片URL
            
        Returns:
            OCR识别结果文本
        """
        try:
            from astrbot.api.provider import ProviderRequest
            
            request = ProviderRequest(
                prompt="请识别这张图片中的所有文字内容，只输出识别到的文字，不要添加任何解释或说明。如果图片中没有文字，请输出：[无文字]",
                image_urls=[image_url]
            )
            
            result = await self.context.call_llm(request)
            
            if result and result.completion_text:
                ocr_text = result.completion_text.strip()
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

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
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
            async for result in self._handle_random(event, ""):
                yield result
            return

    @filter.command("q")
    async def quote_command(self, event: AstrMessageEvent):
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
        
        logger.debug(f"解析消息: args='{args}'")

        match = re.match(r'^(\d+)', args)
        if match:
            count = int(match.group(1))
            if count < 1:
                count = 1
            if count > 20:
                count = 20

        title_match = re.search(r'--title\s+([01])', args)
        if title_match:
            show_title = title_match.group(1) == '1'

        time_match = re.search(r'--time\s+([01])', args)
        if time_match:
            show_time = time_match.group(1) == '1'

        date_match = re.search(r'--date\s+([01])', args)
        if date_match:
            show_date = date_match.group(1) == '1'

        logger.debug(f"解析结果: count={count}, show_title={show_title}, show_time={show_time}, show_date={show_date}")

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
                user_id, nickname, card, title, role = self.parser.parse_sender_info(sender)
                
                msg_content = msg_data_item.get("message", [])
                logger.debug(f"解析消息内容: message 类型={type(msg_content)}, 内容={msg_content}")
                
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

            png_data = await self.renderer.arender(
                render_messages, 
                show_title=show_title, 
                show_time=show_time,
                show_date=show_date
            )

            image_hash = compute_phash(png_data) or "unknown"

            storage_messages = []
            for i, msg_data_item in enumerate(messages_data):
                sender = msg_data_item.get("sender", {})
                user_id, nickname, card, title, role = self.parser.parse_sender_info(sender)
                content, _ = self.parser.parse_message_content(msg_data_item.get("message", []))
                time_str = self.parser.format_time_short(msg_data_item.get("time", 0))
                original_time = msg_data_item.get("time", 0)

                ocr_text = ""
                if self.enable_ocr:
                    image_urls = self._extract_image_urls(msg_data_item.get("message", []))
                    if image_urls:
                        ocr_results = []
                        for img_url in image_urls:
                            ocr_result = await self._ocr_image(img_url)
                            if ocr_result:
                                ocr_results.append(ocr_result)
                        if ocr_results:
                            ocr_text = " ".join(ocr_results)
                            logger.debug(f"消息 {i} OCR识别结果: {ocr_text[:100]}...")

                storage_messages.append({
                    "user_id": user_id,
                    "nickname": nickname,
                    "card": card,
                    "title": title,
                    "role": role,
                    "content": content,
                    "ocr_text": ocr_text,
                    "time_str": time_str,
                    "original_time": original_time
                })

            try:
                self.db.save_record(image_hash, png_data, group_id, storage_messages)
                logger.debug(f"Quotly 记录已保存: hash={image_hash}")
            except Exception as e:
                logger.warning(f"保存 Quotly 记录失败: {e}")

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
            import traceback
            logger.error(f"渲染失败: {e}")
            logger.debug(f"错误堆栈:\n{traceback.format_exc()}")
            yield event.plain_result(f"渲染失败: {str(e)}")

    @filter.command("qsearch")
    async def search_command(self, event: AstrMessageEvent):
        message_str = event.message_str.strip()
        args = re.sub(r'^qsearch\s*', '', message_str)
        async for result in self._handle_search(event, args):
            yield result

    async def _handle_search(self, event: AstrMessageEvent, args: str):
        if not args:
            yield event.plain_result("用法: /qsearch <关键词>\n选项: -u <QQ号>, -g <群号>, -a (全局搜索)")
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

        keyword = keyword.strip()

        try:
            if user_id:
                results = self.db.search_by_user(user_id, group_id, limit=5)
            elif keyword:
                results = self.db.search_by_keyword(keyword, group_id, limit=5)
            else:
                yield event.plain_result("请提供搜索关键词或使用 -u 指定用户")
                return

            if not results:
                search_scope = "所有群" if group_id is None else f"本群"
                yield event.plain_result(f"未在{search_scope}找到匹配的 Quotly 记录")
                return

            for result in results[:3]:
                image_path = result.get('image_path')
                if image_path and Path(image_path).exists():
                    yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
                else:
                    yield event.plain_result(f"图片文件不存在: {image_path}")

            if len(results) > 3:
                yield event.plain_result(f"共找到 {len(results)} 条记录，仅显示前 3 条")

        except Exception as e:
            logger.error(f"搜索失败: {e}")
            yield event.plain_result(f"搜索失败: {str(e)}")

    @filter.command("qrandom")
    async def random_command(self, event: AstrMessageEvent):
        message_str = event.message_str.strip()
        args = re.sub(r'^qrandom\s*', '', message_str)
        async for result in self._handle_random(event, args):
            yield result

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
            results = self.db.get_random(group_id, limit=1)

            if not results:
                search_scope = "所有群" if group_id is None else "本群"
                yield event.plain_result(f"暂无{search_scope} Quotly 记录")
                return

            result = results[0]
            image_path = result.get('image_path')
            if image_path and Path(image_path).exists():
                yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
            else:
                yield event.plain_result(f"图片文件不存在: {image_path}")

        except Exception as e:
            logger.error(f"随机获取失败: {e}")
            yield event.plain_result(f"随机获取失败: {str(e)}")

    @filter.command("qstats")
    async def stats_command(self, event: AstrMessageEvent):
        """
        /qstats - 查看 Quotly 记录统计
        """
        try:
            stats = self.db.get_stats()
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
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def delete_command(self, event: AstrMessageEvent):
        """
        /qdel - 删除语录记录（管理员专用）
        需要回复机器人发送的语录图片消息
        """
        async for result in self._handle_delete(event):
            yield result

    async def _handle_delete(self, event: AstrMessageEvent):
        self.onebot.set_event(event)

        reply_id = self.parser.parse_reply(event)

        if reply_id is None:
            yield event.plain_result("请先回复一条语录图片消息，再使用 /qdel 指令")
            return

        try:
            msg_data = await self.onebot.get_msg(reply_id)

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

                matches = self.db.find_by_hash(image_hash, threshold=5)

                for match in matches:
                    record_id = match.get('id')
                    if self.db.delete_by_id(record_id):
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
                results = self.db.search_by_user(search_user_id, search_group_id, limit=5)
            elif keyword:
                results = self.db.search_by_keyword(keyword, search_group_id, limit=5)
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

            results = self.db.get_random(search_group_id, limit=1)

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
        self.db.close()
        logger.info("Quotlin 插件已卸载")
