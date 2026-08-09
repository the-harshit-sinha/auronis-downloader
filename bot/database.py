"""
Persistent queue + stats storage using SQLite (via aiosqlite).

The queue survives bot restarts: every URL lives as a row in `queue_items`
with a status of pending / processing / completed / failed / cancelled.
On startup, main.py calls `reset_stuck_processing()` to requeue any items
that were mid-flight when the process died, then resumes each chat's queue.
"""
import time
import logging
import aiosqlite
from contextlib import asynccontextmanager

from . import config

logger = logging.getLogger("url_bot.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    first_seen  REAL,
    is_admin    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS queue_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     TEXT,
    chat_id      INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    url          TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending/processing/completed/failed/cancelled
    file_name    TEXT,
    error        TEXT,
    created_at   REAL,
    started_at   REAL,
    completed_at REAL
);

CREATE INDEX IF NOT EXISTS idx_queue_chat_status ON queue_items(chat_id, status);
CREATE INDEX IF NOT EXISTS idx_queue_batch ON queue_items(batch_id);

CREATE TABLE IF NOT EXISTS status_messages (
    chat_id     INTEGER PRIMARY KEY,
    message_id  INTEGER
);
"""


class Database:
    def __init__(self, path: str = None):
        self.path = path or config.DB_PATH
        self._conn: aiosqlite.Connection | None = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        logger.info("Database ready at %s", self.path)

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ---------------------------------------------------------------- users
    async def upsert_user(self, user_id: int, username: str, first_name: str):
        is_admin = 1 if user_id in config.ADMIN_IDS else 0
        await self._conn.execute(
            """INSERT INTO users (user_id, username, first_name, first_seen, is_admin)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
                                                   first_name=excluded.first_name""",
            (user_id, username, first_name, time.time(), is_admin),
        )
        await self._conn.commit()

    async def user_count(self) -> int:
        cur = await self._conn.execute("SELECT COUNT(*) AS c FROM users")
        row = await cur.fetchone()
        return row["c"]

    # ----------------------------------------------------------- queue add
    async def add_urls(self, chat_id: int, user_id: int, urls: list[str], batch_id: str) -> int:
        """Bulk-insert URLs as pending queue items. Returns number inserted."""
        now = time.time()
        rows = [(batch_id, chat_id, user_id, u, "pending", now) for u in urls]
        await self._conn.executemany(
            """INSERT INTO queue_items (batch_id, chat_id, user_id, url, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        await self._conn.commit()
        return len(rows)

    async def url_already_queued(self, chat_id: int, url: str) -> bool:
        cur = await self._conn.execute(
            """SELECT 1 FROM queue_items
               WHERE chat_id=? AND url=? AND status IN ('pending','processing')
               LIMIT 1""",
            (chat_id, url),
        )
        return (await cur.fetchone()) is not None

    # -------------------------------------------------------- queue cycle
    async def get_next_pending(self, chat_id: int):
        cur = await self._conn.execute(
            """SELECT * FROM queue_items
               WHERE chat_id=? AND status='pending'
               ORDER BY id ASC LIMIT 1""",
            (chat_id,),
        )
        return await cur.fetchone()

    async def mark_processing(self, item_id: int):
        await self._conn.execute(
            "UPDATE queue_items SET status='processing', started_at=? WHERE id=?",
            (time.time(), item_id),
        )
        await self._conn.commit()

    async def mark_completed(self, item_id: int, file_name: str):
        await self._conn.execute(
            """UPDATE queue_items SET status='completed', file_name=?, completed_at=?
               WHERE id=?""",
            (file_name, time.time(), item_id),
        )
        await self._conn.commit()

    async def mark_failed(self, item_id: int, error: str):
        await self._conn.execute(
            """UPDATE queue_items SET status='failed', error=?, completed_at=?
               WHERE id=?""",
            (error[:500] if error else None, time.time(), item_id),
        )
        await self._conn.commit()

    async def cancel_pending(self, chat_id: int) -> int:
        cur = await self._conn.execute(
            "UPDATE queue_items SET status='cancelled' WHERE chat_id=? AND status='pending'",
            (chat_id,),
        )
        await self._conn.commit()
        return cur.rowcount

    async def reset_stuck_processing(self):
        """Call once at startup: anything left 'processing' from a crash goes back to pending."""
        cur = await self._conn.execute(
            "UPDATE queue_items SET status='pending', started_at=NULL WHERE status='processing'"
        )
        await self._conn.commit()
        return cur.rowcount

    async def chats_with_pending(self) -> list[int]:
        cur = await self._conn.execute(
            "SELECT DISTINCT chat_id FROM queue_items WHERE status='pending'"
        )
        rows = await cur.fetchall()
        return [r["chat_id"] for r in rows]

    # ------------------------------------------------------------- stats
    async def get_queue_stats(self, chat_id: int) -> dict:
        cur = await self._conn.execute(
            """SELECT status, COUNT(*) AS c FROM queue_items
               WHERE chat_id=? GROUP BY status""",
            (chat_id,),
        )
        rows = await cur.fetchall()
        stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}
        for r in rows:
            stats[r["status"]] = r["c"]
        stats["total"] = sum(stats.values())
        return stats

    async def get_current_processing(self, chat_id: int):
        cur = await self._conn.execute(
            "SELECT * FROM queue_items WHERE chat_id=? AND status='processing' LIMIT 1",
            (chat_id,),
        )
        return await cur.fetchone()

    async def get_failed_urls(self, chat_id: int, batch_id: str = None) -> list[str]:
        if batch_id:
            cur = await self._conn.execute(
                "SELECT url FROM queue_items WHERE chat_id=? AND batch_id=? AND status='failed'",
                (chat_id, batch_id),
            )
        else:
            cur = await self._conn.execute(
                "SELECT url FROM queue_items WHERE chat_id=? AND status='failed'",
                (chat_id,),
            )
        rows = await cur.fetchall()
        return [r["url"] for r in rows]

    async def get_session_stats(self, chat_id: int, since_ts: float) -> dict:
        """completed/failed counts for items finished at or after `since_ts`."""
        cur = await self._conn.execute(
            """SELECT status, COUNT(*) c FROM queue_items
               WHERE chat_id=? AND completed_at >= ? AND status IN ('completed','failed')
               GROUP BY status""",
            (chat_id, since_ts),
        )
        rows = await cur.fetchall()
        result = {"completed": 0, "failed": 0}
        for r in rows:
            result[r["status"]] = r["c"]
        return result

    async def get_session_failed_urls(self, chat_id: int, since_ts: float) -> list[str]:
        cur = await self._conn.execute(
            """SELECT url FROM queue_items
               WHERE chat_id=? AND completed_at >= ? AND status='failed'""",
            (chat_id, since_ts),
        )
        rows = await cur.fetchall()
        return [r["url"] for r in rows]

    async def global_stats(self) -> dict:
        cur = await self._conn.execute(
            "SELECT status, COUNT(*) AS c FROM queue_items GROUP BY status"
        )
        rows = await cur.fetchall()
        stats = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}
        for r in rows:
            stats[r["status"]] = r["c"]
        stats["total"] = sum(stats.values())
        stats["users"] = await self.user_count()
        return stats

    # ------------------------------------------------------- status msg
    async def set_status_message(self, chat_id: int, message_id: int):
        await self._conn.execute(
            """INSERT INTO status_messages (chat_id, message_id) VALUES (?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET message_id=excluded.message_id""",
            (chat_id, message_id),
        )
        await self._conn.commit()

    async def get_status_message(self, chat_id: int):
        cur = await self._conn.execute(
            "SELECT message_id FROM status_messages WHERE chat_id=?", (chat_id,)
        )
        row = await cur.fetchone()
        return row["message_id"] if row else None


db = Database()
