"""
Quotly 数据库模块 - SQLite + FTS5 全文搜索
"""

import sqlite3
import json
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
    """Quotly 数据库管理类"""

    def __init__(self, plugin_name: str = "quotly", db_path: Optional[str] = None, images_dir: Optional[str] = None):
        if db_path is None or images_dir is None:
            if HAS_ASTRBOT_PATH:
                data_path = get_astrbot_data_path()
                if isinstance(data_path, str):
                    data_dir = pathlib.Path(data_path) / "plugin_data" / plugin_name
                else:
                    data_dir = data_path / "plugin_data" / plugin_name
            else:
                plugin_dir = Path(__file__).parent.parent
                data_dir = plugin_dir / "data"
            
            data_dir.mkdir(parents=True, exist_ok=True)

            if db_path is None:
                db_path = str(data_dir / "quotly.db")

            if images_dir is None:
                images_dir = str(data_dir / "images")
                Path(images_dir).mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.images_dir = Path(images_dir)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quotly_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_hash TEXT NOT NULL,
                image_path TEXT NOT NULL,
                group_id INTEGER,
                created_at INTEGER NOT NULL
            )
        """)

        cursor.execute("""
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
            )
        """)

        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS quotly_search USING fts5(
                record_id UNINDEXED,
                nickname,
                card,
                title,
                content,
                tokenize='unicode61'
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_records_group_id ON quotly_records(group_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_records_created_at ON quotly_records(created_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_user_id ON quotly_messages(user_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_record_id ON quotly_messages(record_id)
        """)

        cursor.execute("PRAGMA table_info(quotly_messages)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'ocr_text' not in columns:
            logger.info("数据库迁移: 添加 ocr_text 列")
            cursor.execute("ALTER TABLE quotly_messages ADD COLUMN ocr_text TEXT")

        conn.commit()
        logger.info(f"Quotly 数据库初始化完成: {self.db_path}")

    def save_record(
        self,
        image_hash: str,
        image_data: bytes,
        group_id: Optional[int],
        messages: List[Dict[str, Any]]
    ) -> int:
        conn = self._get_conn()
        cursor = conn.cursor()

        timestamp = int(datetime.now().timestamp())

        image_filename = f"{image_hash}_{timestamp}.png"
        image_path = self.images_dir / image_filename
        with open(image_path, 'wb') as f:
            f.write(image_data)

        cursor.execute("""
            INSERT INTO quotly_records (image_hash, image_path, group_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (image_hash, str(image_path), group_id, timestamp))

        record_id = cursor.lastrowid

        for seq, msg in enumerate(messages):
            cursor.execute("""
                INSERT INTO quotly_messages 
                (record_id, seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                seq,
                msg.get('user_id'),
                msg.get('nickname'),
                msg.get('card'),
                msg.get('title'),
                msg.get('role'),
                msg.get('content'),
                msg.get('ocr_text'),
                msg.get('time_str'),
                msg.get('original_time')
            ))

            cursor.execute("""
                INSERT INTO quotly_search (record_id, nickname, card, title, content)
                VALUES (?, ?, ?, ?, ?)
            """, (
                record_id,
                msg.get('nickname', ''),
                msg.get('card', ''),
                msg.get('title', ''),
                msg.get('content', '') + (' ' + msg.get('ocr_text', '') if msg.get('ocr_text') else '')
            ))

        conn.commit()
        logger.debug(f"保存 Quotly 记录: record_id={record_id}, hash={image_hash}, messages={len(messages)}")
        return record_id

    def search_by_keyword(
        self,
        keyword: str,
        group_id: Optional[int] = None,
        user_id: Optional[int] = None,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()

        fts_query = """
            SELECT DISTINCT r.id, r.image_path, r.image_hash, r.group_id, r.created_at
            FROM quotly_records r
            WHERE r.id IN (
                SELECT s.record_id FROM quotly_search s 
                WHERE quotly_search MATCH ?
            )
        """
        
        fts_keyword = self._prepare_fts_keyword(keyword)
        params = [fts_keyword]

        if group_id is not None:
            fts_query += " AND r.group_id = ?"
            params.append(group_id)

        fts_query += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(fts_query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            record = dict(row)
            record['messages'] = self._get_messages_by_record_id(record['id'])
            results.append(record)

        return results

    def _prepare_fts_keyword(self, keyword: str) -> str:
        """
        准备 FTS5 搜索关键词
        处理特殊字符并添加通配符
        
        Args:
            keyword: 原始搜索关键词
            
        Returns:
            处理后的 FTS5 搜索字符串
        """
        keyword = keyword.strip()
        
        if not keyword:
            return '""'
        
        fts_special_chars = ['"', "'", '*', '^', '(', ')', '{', '}', '[', ']']
        for char in fts_special_chars:
            keyword = keyword.replace(char, ' ')
        
        words = keyword.split()
        if not words:
            return '""'
        
        fts_words = []
        for word in words:
            if word:
                fts_words.append(f'"{word}"*')
        
        return ' OR '.join(fts_words) if fts_words else '""'

    def search_by_user(
        self,
        user_id: int,
        group_id: Optional[int] = None,
        limit: int = 10,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()

        base_query = """
            SELECT DISTINCT r.id, r.image_path, r.image_hash, r.group_id, r.created_at
            FROM quotly_records r
            JOIN quotly_messages m ON m.record_id = r.id
            WHERE m.user_id = ?
        """
        params = [user_id]

        if group_id is not None:
            base_query += " AND r.group_id = ?"
            params.append(group_id)

        base_query += " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(base_query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            record = dict(row)
            record['messages'] = self._get_messages_by_record_id(record['id'])
            results.append(record)

        return results

    def get_random(
        self,
        group_id: Optional[int] = None,
        limit: int = 1
    ) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()

        if group_id is not None:
            cursor.execute("""
                SELECT id, image_path, image_hash, group_id, created_at
                FROM quotly_records
                WHERE group_id = ?
                ORDER BY RANDOM()
                LIMIT ?
            """, (group_id, limit))
        else:
            cursor.execute("""
                SELECT id, image_path, image_hash, group_id, created_at
                FROM quotly_records
                ORDER BY RANDOM()
                LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()

        results = []
        for row in rows:
            record = dict(row)
            record['messages'] = self._get_messages_by_record_id(record['id'])
            results.append(record)

        return results

    def _get_messages_by_record_id(self, record_id: int) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time
            FROM quotly_messages
            WHERE record_id = ?
            ORDER BY seq
        """, (record_id,))

        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, int]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM quotly_records")
        total_records = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM quotly_messages")
        total_messages = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT group_id) FROM quotly_records WHERE group_id IS NOT NULL")
        total_groups = cursor.fetchone()[0]

        return {
            'total_records': total_records,
            'total_messages': total_messages,
            'total_groups': total_groups
        }

    def find_by_hash(self, image_hash: str, threshold: int = 5) -> List[Dict[str, Any]]:
        """
        根据图片hash查找记录（支持模糊匹配）

        Args:
            image_hash: 要匹配的hash值
            threshold: 汉明距离阈值，小于等于此值认为匹配

        Returns:
            匹配的记录列表
        """
        from utils.image_hash import hamming_distance

        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, image_path, image_hash, group_id, created_at
            FROM quotly_records
        """)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            record = dict(row)
            stored_hash = record.get('image_hash', '')
            if stored_hash:
                distance = hamming_distance(image_hash, stored_hash)
                if 0 <= distance <= threshold:
                    record['hamming_distance'] = distance
                    record['messages'] = self._get_messages_by_record_id(record['id'])
                    results.append(record)

        results.sort(key=lambda x: x.get('hamming_distance', 999))
        return results

    def delete_by_id(self, record_id: int) -> bool:
        """
        根据记录ID删除语录记录

        Args:
            record_id: 记录ID

        Returns:
            是否删除成功
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT image_path FROM quotly_records WHERE id = ?
        """, (record_id,))
        row = cursor.fetchone()

        if not row:
            return False

        image_path = row[0]

        cursor.execute("DELETE FROM quotly_search WHERE record_id = ?", (record_id,))
        cursor.execute("DELETE FROM quotly_messages WHERE record_id = ?", (record_id,))
        cursor.execute("DELETE FROM quotly_records WHERE id = ?", (record_id,))

        conn.commit()

        if image_path:
            try:
                Path(image_path).unlink(missing_ok=True)
                logger.debug(f"已删除图片文件: {image_path}")
            except Exception as e:
                logger.warning(f"删除图片文件失败: {e}")

        logger.info(f"已删除语录记录: record_id={record_id}")
        return True

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.debug("Quotly 数据库连接已关闭")
