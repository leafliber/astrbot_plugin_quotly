"""
测试数据库模块（独立版本，不依赖 AstrBot）
"""
import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import tempfile


class QuotlyDatabaseTest:
    """测试用数据库类（简化版，不依赖 AstrBot）"""

    def __init__(self, db_path: str, images_dir: str):
        self.db_path = db_path
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    @staticmethod
    def _build_search_text(messages: List[Dict[str, Any]]) -> str:
        """从消息列表构建可搜索文本"""
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

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quotly_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_hash TEXT NOT NULL,
                image_path TEXT NOT NULL,
                group_id INTEGER,
                created_at INTEGER NOT NULL,
                search_text TEXT DEFAULT ''
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
                reply_nickname TEXT,
                reply_content TEXT,
                FOREIGN KEY (record_id) REFERENCES quotly_records(id) ON DELETE CASCADE
            )
        """)

        conn.commit()
        print(f"数据库初始化完成: {self.db_path}")

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

        import hashlib
        content_hash = hashlib.sha256(image_data).hexdigest()[:32]
        image_filename = f"{content_hash}.png"
        image_path = self.images_dir / image_filename
        with open(image_path, 'wb') as f:
            f.write(image_data)

        search_text = self._build_search_text(messages)
        cursor.execute("""
            INSERT INTO quotly_records (image_hash, image_path, group_id, created_at, search_text)
            VALUES (?, ?, ?, ?, ?)
        """, (image_hash, str(image_path), group_id, timestamp, search_text))

        record_id = cursor.lastrowid

        for seq, msg in enumerate(messages):
            cursor.execute("""
                INSERT INTO quotly_messages
                (record_id, seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time, reply_nickname, reply_content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                msg.get('original_time'),
                msg.get('reply_nickname'),
                msg.get('reply_content')
            ))

        conn.commit()
        return record_id

    def search_by_keyword(self, keyword: str, group_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()

        like_pattern = f"%{keyword}%"
        base_query = """
            SELECT r.id, r.image_path, r.image_hash, r.group_id, r.created_at
            FROM quotly_records r
            WHERE r.search_text LIKE ?
        """
        params: list = [like_pattern]

        if group_id is not None:
            base_query += " AND r.group_id = ?"
            params.append(group_id)

        base_query += " ORDER BY r.created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(base_query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            record = dict(row)
            record['messages'] = self._get_messages_by_record_id(record['id'])
            results.append(record)

        return results

    def search_by_user(self, user_id: int, group_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
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

        base_query += " ORDER BY r.created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(base_query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            record = dict(row)
            record['messages'] = self._get_messages_by_record_id(record['id'])
            results.append(record)

        return results

    def get_random(self, group_id: Optional[int] = None, limit: int = 1) -> List[Dict[str, Any]]:
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
            SELECT seq, user_id, nickname, card, title, role, content, ocr_text, time_str, original_time, reply_nickname, reply_content
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

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


def test_database():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        images_dir = os.path.join(tmpdir, "images")

        db = QuotlyDatabaseTest(db_path, images_dir)

        print("1. 测试保存记录...")
        test_messages = [
            {
                "user_id": 12345,
                "nickname": "测试用户",
                "card": "测试名片",
                "title": "测试头衔",
                "role": "admin",
                "content": "这是一条测试消息",
                "ocr_text": "",
                "time_str": "12:00",
                "original_time": 1700000000,
                "reply_nickname": "",
                "reply_content": ""
            }
        ]

        test_image_data = b"fake_png_data_for_testing"
        record_id = db.save_record("test_hash_123", test_image_data, 123456, test_messages)
        print(f"   记录 ID: {record_id}")

        print("2. 测试中文关键词搜索...")
        results = db.search_by_keyword("测试")
        print(f"   搜索 '测试' 结果数: {len(results)}")
        assert len(results) == 1, f"预期 1 条结果，实际 {len(results)}"
        if results:
            print(f"   第一条记录消息数: {len(results[0]['messages'])}")
            print(f"   消息内容: {results[0]['messages'][0]['content']}")

        print("3. 测试多字中文搜索...")
        results = db.search_by_keyword("测试消息")
        print(f"   搜索 '测试消息' 结果数: {len(results)}")
        assert len(results) == 1, f"预期 1 条结果，实际 {len(results)}"

        print("4. 测试名片搜索...")
        results = db.search_by_keyword("名片")
        print(f"   搜索 '名片' 结果数: {len(results)}")
        assert len(results) == 1

        print("5. 测试用户搜索...")
        results = db.search_by_user(12345)
        print(f"   搜索结果数: {len(results)}")

        print("6. 测试随机获取...")
        results = db.get_random()
        print(f"   随机结果数: {len(results)}")

        print("7. 测试统计...")
        stats = db.get_stats()
        print(f"   统计: {stats}")

        print("8. 测试回复信息搜索...")
        reply_messages = [
            {
                "user_id": 54321,
                "nickname": "用户B",
                "content": "回复测试",
                "ocr_text": "",
                "reply_nickname": "用户A",
                "reply_content": "原始消息内容"
            }
        ]
        db.save_record("test_hash_reply", b"reply_image_data", 123456, reply_messages)
        results = db.search_by_keyword("原始消息")
        print(f"   搜索 '原始消息' (回复内容) 结果数: {len(results)}")
        assert len(results) == 1

        db.close()
        print("\n所有测试通过!")


if __name__ == "__main__":
    test_database()
