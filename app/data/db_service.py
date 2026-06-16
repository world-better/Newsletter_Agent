"""DB layer — only aiosqlite lives here. Swap for postgres by replacing this file."""
import aiosqlite


class DBService:
    def __init__(self, db_path: str):
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self):
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA busy_timeout=5000;
            PRAGMA wal_autocheckpoint=1000;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments TEXT,
                result TEXT,
                logged_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (message_id) REFERENCES messages(id)
            );
            CREATE TABLE IF NOT EXISTS rss_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, name)
            );
        """)
        await self._conn.commit()

    async def insert_message(self, message_id: str, user_id: str, role: str, content: str):
        await self._conn.execute(
            "INSERT INTO messages(id, user_id, role, content) VALUES(?,?,?,?)",
            (message_id, user_id, role, content)
        )
        await self._conn.commit()

    async def get_message_by_id(self, message_id: str):
        cursor = await self._conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        )
        return await cursor.fetchone()

    async def log_tool_call(self, message_id: str, tool_name: str, arguments: str, result: str):
        await self._conn.execute(
            "INSERT INTO tool_calls(message_id, tool_name, arguments, result) VALUES(?,?,?,?)",
            (message_id, tool_name, arguments, result)
        )
        await self._conn.commit()

    async def get_history(self, user_id: str, limit: int = 50):
        cursor = await self._conn.execute(
            "SELECT * FROM messages WHERE user_id = ? ORDER BY created_at ASC LIMIT ?",
            (user_id, limit)
        )
        return await cursor.fetchall()

    async def close(self):
        if self._conn:
            await self._conn.close()

    # ── RSS subscriptions ──────────────────────────────────────────────────

    async def insert_subscription(self, user_id: str, name: str, url: str):
        await self._conn.execute(
            "INSERT OR REPLACE INTO rss_subscriptions(user_id, name, url) VALUES(?,?,?)",
            (user_id, name, url)
        )
        await self._conn.commit()

    async def list_subscriptions(self, user_id: str) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT name, url FROM rss_subscriptions WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,)
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def delete_subscription(self, user_id: str, name: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM rss_subscriptions WHERE user_id = ? AND name = ?",
            (user_id, name)
        )
        await self._conn.commit()
        return cursor.rowcount > 0
