"""
Quotly 数据库模块 - SQLite + FTS5 全文搜索（异步版本）
使用 aiosqlite 实现非阻塞数据库操作
"""

import asyncio
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
                created_at INTEGER NOT NULL
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
                FOREIGN KEY (record_id) REFERENCES quotly_records(id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS quotly_search USING fts5(
                record_id UNINDEXED,
                nickname,
                card,
                title,
                content,
                tokenize='unicode61'
            );

            CREATE INDEX IF NOT EXISTS idx_records_group_id ON quotly_records(group_id);
            CREATE INDEX IF NOT EXISTS idx_records_created_at ON quotly_records(created_at);
            CREATE INDEX IF NOT EXISTS idx_messages_user_id ON quotly_messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_record_id ON quotly_messages(record_id);
        """)

        # 检查并添加 ocr_text 列
        cursor = await conn.execute("PRAGMA table_info(quotly_messages)")
        columns = [col[1] for col in await cursor.fetchall()]
        if 'ocr_text' not in columns:
            logger.info("数据库迁移: 添加 ocr_text 列")
            await conn.execute("ALTER TABLE quotly_messages ADD COLUMN ocr_text TEXT")

        await conn.commit()
        logger.info(f"Quotly 数据库初始化完成: {self.db_path}")

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

        # 保存图片文件
        image_path = self.images_dir / f"{image_hash}_{timestamp}.png"
        image_path.write_bytes(image_data)

        # 插入记录
        async with self._lock:
            cursor = await conn.execute(
                "INSERT INTO quotly_records (image_hash, image_path, group_id, created_at) VALUES (?, ?, ?, ?)",
                (image_hash, str(image_path), group_id, timestamp)
            )
            record_id = cursor.lastrowid

            for seq, msg in enumerate(messages):
                await conn.execute(
                    """INSERT INTO quotly_messages
                    (record_id, seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, seq, msg.get('user_id'), msg.get('nickname'), msg.get('card'),
                     msg.get('title'), msg.get('role'), msg.get('content'), msg.get('ocr_text'),
                     msg.get('time_str'), msg.get('original_time'))
                )
                await conn.execute(
                    "INSERT INTO quotly_search (record_id, nickname, card, title, content) VALUES (?, ?, ?, ?, ?)",
                    (record_id, msg.get('nickname', ''), msg.get('card', ''), msg.get('title', ''),
                     msg.get('content', '') + (' ' + msg.get('ocr_text', '') if msg.get('ocr_text') else ''))
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
            for seq, msg in enumerate(messages):
                ocr_text = msg.get('ocr_text', '')
                if ocr_text:
                    await conn.execute(
                        "UPDATE quotly_messages SET ocr_text = ? WHERE record_id = ? AND seq = ?",
                        (ocr_text, record_id, seq)
                    )
                    
                    await conn.execute(
                        "DELETE FROM quotly_search WHERE record_id = ?",
                        (record_id,)
                    )
                    
                    for m_idx, m in enumerate(messages):
                        await conn.execute(
                            "INSERT INTO quotly_search (record_id, nickname, card, title, content) VALUES (?, ?, ?, ?, ?)",
                            (record_id, m.get('nickname', ''), m.get('card', ''), m.get('title', ''),
                             m.get('content', '') + (' ' + m.get('ocr_text', '') if m.get('ocr_text') else ''))
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

        query = """
            SELECT DISTINCT r.id, r.image_path, r.image_hash, r.group_id, r.created_at
            FROM quotly_records r
            WHERE r.id IN (SELECT s.record_id FROM quotly_search s WHERE quotly_search MATCH ?)
        """
        params = [self._prepare_fts_keyword(keyword)]

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
            "SELECT seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time FROM quotly_messages WHERE record_id = ? ORDER BY seq",
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

    async def find_by_hash(self, image_hash: str, threshold: int = 5) -> List[Dict[str, Any]]:
        """根据图片hash查找记录"""
        from utils.image_hash import hamming_distance

        conn = await self._get_conn()
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
            await conn.execute("DELETE FROM quotly_search WHERE record_id = ?", (record_id,))
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

    def _prepare_fts_keyword(self, keyword: str) -> str:
        """准备 FTS5 搜索关键词"""
        keyword = keyword.strip()
        if not keyword:
            return '""'

        for char in ['"', "'", '*', '^', '(', ')', '{', '}', '[', ']']:
            keyword = keyword.replace(char, ' ')

        words = [f'"{w}"*' for w in keyword.split() if w]
        return ' OR '.join(words) if words else '""'

    async def close(self):
        """关闭数据库连接"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.debug("Quotly 数据库连接已关闭")