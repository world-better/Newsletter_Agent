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
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT DEFAULT '新会话',
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        await self._conn.commit()

        # Migrate: add session_id to messages if column doesn't exist
        try:
            await self._conn.execute("ALTER TABLE messages ADD COLUMN session_id TEXT REFERENCES sessions(id)")
            await self._conn.commit()
        except Exception:
            pass  # column already exists

        # Pre-seed default subscriptions (shared baseline for all users)
        await self._conn.executemany(
            "INSERT OR IGNORE INTO rss_subscriptions(user_id, name, url) VALUES(?,?,?)",
            [
                ("default_user", "Hacker News 头条", "https://hnrss.org/frontpage"),
                ("default_user", "NYT Technology", "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
                ("default_user", "BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
                ("default_user", "知乎日报", "https://rsshub.rssforever.com/zhihu/daily"),
                ("default_user", "V2EX 最新", "https://rsshub.rssforever.com/v2ex/topics/latest"),
            ],
        )
        await self._conn.commit()

    async def insert_message(self, message_id: str, user_id: str, role: str, content: str, session_id: str | None = None):
        await self._conn.execute(
            "INSERT INTO messages(id, user_id, role, content, session_id) VALUES(?,?,?,?,?)",
            (message_id, user_id, role, content, session_id)
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

    # ── Sessions ───────────────────────────────────────────────────────────

    async def create_session(self, user_id: str, title: str = "新会话") -> dict:
        sid = str(__import__("uuid").uuid4())
        await self._conn.execute(
            "INSERT INTO sessions(id, user_id, title) VALUES(?,?,?)",
            (sid, user_id, title)
        )
        await self._conn.commit()
        return {"id": sid, "user_id": user_id, "title": title}

    async def list_sessions(self, user_id: str) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT id, title, created_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        return [dict(r) for r in await cursor.fetchall()]

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
