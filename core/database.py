"""
Quotly 数据库模块 - SQLite + LIKE 全文搜索（异步版本）
使用 aiosqlite 实现非阻塞数据库操作
"""

import asyncio
import hashlib
import aiosqlite
import pathlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from astrbot.api import logger

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    HAS_ASTRBOT_PATH = True
except ImportError:
    HAS_ASTRBOT_PATH = False


class QuotlyDatabase:
    """Quotly 数据库管理类（异步版本）"""

    def __init__(self, plugin_name: str = "quotly", db_path: Optional[str] = None, images_dir: Optional[str] = None):
        if db_path is None or images_dir is None:
            if HAS_ASTRBOT_PATH:
                data_path = get_astrbot_data_path()
                data_dir = (pathlib.Path(data_path) if isinstance(data_path, str)
                           else data_path) / "plugin_data" / plugin_name
            else:
                data_dir = Path(__file__).parent.parent / "data"

            data_dir.mkdir(parents=True, exist_ok=True)

            if db_path is None:
                db_path = str(data_dir / "quotly.db")
            if images_dir is None:
                images_dir = str(data_dir / "images")
                Path(images_dir).mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.images_dir = Path(images_dir)
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def _get_conn(self) -> aiosqlite.Connection:
        """获取数据库连接"""
        async with self._lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self.db_path)
                self._conn.row_factory = aiosqlite.Row
                if not self._initialized:
                    await self._init_db()
                    self._initialized = True
        return self._conn

    async def _init_db(self):
        """初始化数据库表结构"""
        conn = self._conn

        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS quotly_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_hash TEXT NOT NULL,
                image_path TEXT NOT NULL,
                group_id INTEGER,
                created_at INTEGER NOT NULL,
                search_text TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS quotly_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                user_id INTEGER,
                nickname TEXT,
                card TEXT,
                title TEXT,
                role TEXT,
                content TEXT,
                ocr_text TEXT,
                time_str TEXT,
                original_time INTEGER,
                reply_nickname TEXT,
                reply_content TEXT,
                FOREIGN KEY (record_id) REFERENCES quotly_records(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_records_group_id ON quotly_records(group_id);
            CREATE INDEX IF NOT EXISTS idx_records_created_at ON quotly_records(created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_user_id ON quotly_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_record_id ON quotly_messages(record_id);
        """)

        # 列迁移（兼容已有测试数据库）
        cursor = await conn.execute("PRAGMA table_info(quotly_records)")
        columns = [col[1] for col in await cursor.fetchall()]
        if 'search_text' not in columns:
            await conn.execute("ALTER TABLE quotly_records ADD COLUMN search_text TEXT DEFAULT ''")

        cursor = await conn.execute("PRAGMA table_info(quotly_messages)")
        columns = [col[1] for col in await cursor.fetchall()]
        if 'ocr_text' not in columns:
            await conn.execute("ALTER TABLE quotly_messages ADD COLUMN ocr_text TEXT")
        if 'reply_nickname' not in columns:
            await conn.execute("ALTER TABLE quotly_messages ADD COLUMN reply_nickname TEXT")
        if 'reply_content' not in columns:
            await conn.execute("ALTER TABLE quotly_messages ADD COLUMN reply_content TEXT")

        # 移除旧的 FTS5 虚拟表
        try:
            await conn.execute("DROP TABLE IF EXISTS quotly_search")
        except Exception:
            pass

        await conn.commit()
        logger.info(f"Quotly 数据库初始化完成: {self.db_path}")

    @staticmethod
    def _build_search_text(messages: List[Dict[str, Any]]) -> str:
        """从消息列表构建可搜索文本（包含图片中所有可见文字）"""
        parts = []
        for msg in messages:
            for key in ('nickname', 'card', 'title', 'content', 'ocr_text'):
                val = msg.get(key, '')
                if val:
                    parts.append(val)
            for key in ('reply_nickname', 'reply_content'):
                val = msg.get(key, '')
                if val:
                    parts.append(val)
        return ' '.join(parts)

    async def save_record(
        self,
        image_hash: str,
        image_data: bytes,
        group_id: Optional[int],
        messages: List[Dict[str, Any]]
    ) -> int:
        """保存语录记录"""
        conn = await self._get_conn()
        timestamp = int(datetime.now().timestamp())

        # 保存图片文件（使用 SHA-256 内容哈希命名）
        content_hash = hashlib.sha256(image_data).hexdigest()[:32]
        image_path = self.images_dir / f"{content_hash}.png"
        image_path.write_bytes(image_data)

        # 插入记录
        search_text = self._build_search_text(messages)
        async with self._lock:
            cursor = await conn.execute(
                "INSERT INTO quotly_records (image_hash, image_path, group_id, created_at, search_text) VALUES (?, ?, ?, ?, ?)",
                (image_hash, str(image_path), group_id, timestamp, search_text)
            )
            record_id = cursor.lastrowid

            for seq, msg in enumerate(messages):
                await conn.execute(
                    """INSERT INTO quotly_messages
                    (record_id, seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time, reply_nickname, reply_content)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, seq, msg.get('user_id'), msg.get('nickname'), msg.get('card'),
                     msg.get('title'), msg.get('role'), msg.get('content'), msg.get('ocr_text'),
                     msg.get('time_str'), msg.get('original_time'),
                     msg.get('reply_nickname'), msg.get('reply_content'))
                )

            await conn.commit()

        logger.debug(f"保存 Quotly 记录: record_id={record_id}, hash={image_hash}")
        return record_id

    async def update_ocr_text(self, image_hash: str, messages: List[Dict[str, Any]]) -> bool:
        """
        更新记录的 OCR 文本
        
        Args:
            image_hash: 图片 hash 值
            messages: 更新后的消息列表（包含 ocr_text）
            
        Returns:
            是否更新成功
        """
        conn = await self._get_conn()
        
        cursor = await conn.execute(
            "SELECT id FROM quotly_records WHERE image_hash = ?",
            (image_hash,)
        )
        row = await cursor.fetchone()
        
        if not row:
            logger.warning(f"未找到记录: hash={image_hash}")
            return False
        
        record_id = row['id']
        
        async with self._lock:
            has_ocr_update = False
            for seq, msg in enumerate(messages):
                ocr_text = msg.get('ocr_text', '')
                if ocr_text:
                    await conn.execute(
                        "UPDATE quotly_messages SET ocr_text = ? WHERE record_id = ? AND seq = ?",
                        (ocr_text, record_id, seq)
                    )
                    has_ocr_update = True

            if has_ocr_update:
                search_text = self._build_search_text(messages)
                await conn.execute(
                    "UPDATE quotly_records SET search_text = ? WHERE id = ?",
                    (search_text, record_id)
                )

            await conn.commit()
        
        logger.debug(f"更新 OCR 文本: record_id={record_id}")
        return True

    async def search_by_keyword(
        self,
        keyword: str,
        group_id: Optional[int] = None,
        user_id: Optional[int] = None,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """根据关键词搜索语录"""
        conn = await self._get_conn()

        like_pattern = f"%{keyword}%"
        query = """
            SELECT r.id, r.image_path, r.image_hash, r.group_id, r.created_at
            FROM quotly_records r
            WHERE r.search_text LIKE ?
        """
        params: list = [like_pattern]

        if group_id is not None:
            query += " AND r.group_id = ?"
            params.append(group_id)

        query += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            record = dict(row)
            record['messages'] = await self._get_messages_by_record_id(record['id'])
            results.append(record)

        return results

    async def search_by_user(
        self,
        user_id: int,
        group_id: Optional[int] = None,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """根据用户搜索语录"""
        conn = await self._get_conn()

        query = """
            SELECT DISTINCT r.id, r.image_path, r.image_hash, r.group_id, r.created_at
            FROM quotly_records r JOIN quotly_messages m ON m.record_id = r.id
            WHERE m.user_id = ?
        """
        params = [user_id]

        if group_id is not None:
            query += " AND r.group_id = ?"
            params.append(group_id)

        query += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()

        return [dict(row, messages=await self._get_messages_by_record_id(row['id'])) for row in rows]

    async def get_random(self, group_id: Optional[int] = None, limit: int = 1) -> List[Dict[str, Any]]:
        """随机获取语录"""
        conn = await self._get_conn()

        if group_id is not None:
            cursor = await conn.execute(
                "SELECT id, image_path, image_hash, group_id, created_at FROM quotly_records WHERE group_id = ? ORDER BY RANDOM() LIMIT ?",
                (group_id, limit)
            )
        else:
            cursor = await conn.execute(
                "SELECT id, image_path, image_hash, group_id, created_at FROM quotly_records ORDER BY RANDOM() LIMIT ?",
                (limit,)
            )

        rows = await cursor.fetchall()
        return [dict(row, messages=await self._get_messages_by_record_id(row['id'])) for row in rows]

    async def _get_messages_by_record_id(self, record_id: int) -> List[Dict[str, Any]]:
        """根据记录ID获取消息列表"""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time, reply_nickname, reply_content FROM quotly_messages WHERE record_id = ? ORDER BY seq",
            (record_id,)
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        conn = await self._get_conn()

        cursor = await conn.execute("SELECT COUNT(*) FROM quotly_records")
        total_records = (await cursor.fetchone())[0]

        cursor = await conn.execute("SELECT COUNT(*) FROM quotly_messages")
        total_messages = (await cursor.fetchone())[0]

        cursor = await conn.execute("SELECT COUNT(DISTINCT group_id) FROM quotly_records WHERE group_id IS NOT NULL")
        total_groups = (await cursor.fetchone())[0]

        return {'total_records': total_records, 'total_messages': total_messages, 'total_groups': total_groups}

    async def find_by_hash(self, image_hash: str, threshold: int = 5, group_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """根据图片hash查找记录"""
        from utils.image_hash import hamming_distance

        conn = await self._get_conn()
        if group_id is not None:
            cursor = await conn.execute(
                "SELECT id, image_path, image_hash, group_id, created_at FROM quotly_records WHERE group_id = ?",
                (group_id,)
            )
        else:
            cursor = await conn.execute("SELECT id, image_path, image_hash, group_id, created_at FROM quotly_records")
        rows = await cursor.fetchall()

        results = []
        for row in rows:
            stored_hash = row['image_hash']
            if stored_hash:
                distance = hamming_distance(image_hash, stored_hash)
                if 0 <= distance <= threshold:
                    results.append({
                        **dict(row),
                        'hamming_distance': distance,
                        'messages': await self._get_messages_by_record_id(row['id'])
                    })

        results.sort(key=lambda x: x.get('hamming_distance', 999))
        return results

    async def delete_by_id(self, record_id: int) -> bool:
        """根据记录ID删除语录记录"""
        conn = await self._get_conn()

        cursor = await conn.execute("SELECT image_path FROM quotly_records WHERE id = ?", (record_id,))
        row = await cursor.fetchone()

        if not row:
            return False

        async with self._lock:
            await conn.execute("DELETE FROM quotly_messages WHERE record_id = ?", (record_id,))
            await conn.execute("DELETE FROM quotly_records WHERE id = ?", (record_id,))
            await conn.commit()

        image_path = row[0]
        if image_path:
            try:
                Path(image_path).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"删除图片文件失败: {e}")

        logger.info(f"已删除语录记录: record_id={record_id}")
        return True

    async def get_records(
        self,
        group_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """分页获取语录记录列表"""
        conn = await self._get_conn()

        where = "WHERE r.group_id = ?" if group_id is not None else ""
        params_count: list = [group_id] if group_id is not None else []

        cursor = await conn.execute(f"SELECT COUNT(*) FROM quotly_records r {where}", params_count)
        total = (await cursor.fetchone())[0]

        params_query: list = [group_id] if group_id is not None else []
        params_query.extend([limit, offset])

        cursor = await conn.execute(f"""
            SELECT r.id, r.image_hash, r.image_path, r.group_id, r.created_at,
                   m.nickname AS preview_nickname, m.content AS preview_content
            FROM quotly_records r
            LEFT JOIN quotly_messages m ON m.record_id = r.id
                AND m.seq = (SELECT MIN(m2.seq) FROM quotly_messages m2 WHERE m2.record_id = r.id)
            {"WHERE r.group_id = ?" if group_id is not None else ""}
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
        """, params_query)
        rows = await cursor.fetchall()

        records = []
        for row in rows:
            record = dict(row)
            record['image_exists'] = Path(record['image_path']).exists() if record['image_path'] else False
            records.append(record)

        return {"records": records, "total": total, "limit": limit, "offset": offset}

    async def get_image_path(self, record_id: int) -> Optional[str]:
        """获取记录的图片路径（轻量查询，不加载消息）"""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT image_path FROM quotly_records WHERE id = ?",
            (record_id,)
        )
        row = await cursor.fetchone()
        return row['image_path'] if row else None

    async def get_record_by_id(self, record_id: int) -> Optional[Dict[str, Any]]:
        """获取单条语录记录详情"""
        conn = await self._get_conn()

        cursor = await conn.execute(
            "SELECT id, image_hash, image_path, group_id, created_at FROM quotly_records WHERE id = ?",
            (record_id,)
        )
        row = await cursor.fetchone()

        if not row:
            return None

        record = dict(row)
        record['image_exists'] = Path(record['image_path']).exists() if record['image_path'] else False
        record['messages'] = await self._get_messages_by_record_id(record_id)
        return record

    async def update_messages(self, record_id: int, messages: List[Dict[str, Any]]) -> bool:
        """更新消息的内容和 OCR 文本，并重建搜索文本"""
        conn = await self._get_conn()

        cursor = await conn.execute("SELECT id FROM quotly_records WHERE id = ?", (record_id,))
        if not await cursor.fetchone():
            return False

        existing = await self._get_messages_by_record_id(record_id)
        existing_map = {m['seq']: m for m in existing}

        async with self._lock:
            for msg in messages:
                seq = msg.get('seq')
                if seq is None or seq not in existing_map:
                    continue
                content = msg.get('content', existing_map[seq].get('content', ''))
                ocr_text = msg.get('ocr_text', existing_map[seq].get('ocr_text', ''))
                await conn.execute(
                    "UPDATE quotly_messages SET content = ?, ocr_text = ? WHERE record_id = ? AND seq = ?",
                    (content, ocr_text, record_id, seq)
                )

            # 重新读取所有消息并重建 search_text
            cursor = await conn.execute(
                "SELECT seq, user_id, nickname, card, title, role, content, ocr_text, reply_nickname, reply_content FROM quotly_messages WHERE record_id = ? ORDER BY seq",
                (record_id,)
            )
            all_messages = [dict(row) for row in await cursor.fetchall()]
            search_text = self._build_search_text(all_messages)
            await conn.execute(
                "UPDATE quotly_records SET search_text = ? WHERE id = ?",
                (search_text, record_id)
            )

            await conn.commit()

        logger.debug(f"更新消息内容: record_id={record_id}")
        return True

    async def get_groups(self) -> List[Dict[str, Any]]:
        """获取所有群组及其记录数"""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT group_id, COUNT(*) as count FROM quotly_records WHERE group_id IS NOT NULL GROUP BY group_id ORDER BY count DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_all_records_for_export(self) -> List[Dict[str, Any]]:
        """获取全部记录（含消息）用于导出"""
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, image_hash, image_path, group_id, created_at FROM quotly_records ORDER BY id"
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            record = dict(row)
            record['messages'] = await self._get_messages_by_record_id(record['id'])
            results.append(record)
        return results

    async def search_count(self, keyword: str, group_id: Optional[int] = None) -> int:
        """获取搜索结果总数"""
        conn = await self._get_conn()
        like_pattern = f"%{keyword}%"
        query = "SELECT COUNT(*) FROM quotly_records r WHERE r.search_text LIKE ?"
        params: list = [like_pattern]
        if group_id is not None:
            query += " AND r.group_id = ?"
            params.append(group_id)
        cursor = await conn.execute(query, params)
        return (await cursor.fetchone())[0]

    async def close(self):
        """关闭数据库连接"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.debug("Quotly 数据库连接已关闭")