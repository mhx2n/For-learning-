import sqlite3
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "bot_data.db")


class Database:
    def __init__(self):
        self.db_path = DB_PATH

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        """ডেটাবেস তৈরি করো"""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    added_by INTEGER,
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fb_post_id TEXT UNIQUE,
                    page_slug TEXT,
                    text TEXT,
                    post_url TEXT,
                    status TEXT DEFAULT 'pending',
                    fetched_at TEXT,
                    posted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT '0'
                );
            """)
            # Default stats
            for key in ["total_fetched", "approved_posted", "rejected", "bandwidth_used_kb", "last_fetch"]:
                conn.execute(
                    "INSERT OR IGNORE INTO stats (key, value) VALUES (?, ?)",
                    (key, "0" if key != "last_fetch" else "কখনো না")
                )
            conn.commit()
        logger.info("✅ Database তৈরি হয়েছে।")

    # ─── PAGES ───────────────────────────────────────────────────────────

    def add_page(self, slug: str, url: str, added_by: int) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO pages (slug, url, added_by) VALUES (?, ?, ?)",
                (slug, url, added_by)
            )
            conn.commit()
            return cur.lastrowid

    def get_page_by_slug(self, slug: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM pages WHERE slug=?", (slug,)).fetchone()
            return dict(row) if row else None

    def get_all_pages(self) -> list:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM pages ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def get_active_pages(self) -> list:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM pages WHERE active=1").fetchall()
            return [dict(r) for r in rows]

    def remove_page(self, page_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM pages WHERE id=?", (page_id,))
            conn.commit()
            return cur.rowcount > 0

    # ─── POSTS ───────────────────────────────────────────────────────────

    def save_post(self, fb_post_id: str, page_slug: str, text: str,
                  post_url: str, fetched_at: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO posts
                   (fb_post_id, page_slug, text, post_url, status, fetched_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (fb_post_id, page_slug, text, post_url, fetched_at)
            )
            conn.commit()
            return cur.lastrowid

    def post_exists(self, fb_post_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM posts WHERE fb_post_id=?", (fb_post_id,)
            ).fetchone()
            return row is not None

    def get_post_by_id(self, post_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
            return dict(row) if row else None

    def get_pending_posts(self, limit: int = 10) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM posts WHERE status='pending' ORDER BY fetched_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def update_post_status(self, post_id: int, status: str):
        from datetime import datetime
        with self._conn() as conn:
            posted_at = datetime.now().isoformat() if status == "posted" else None
            conn.execute(
                "UPDATE posts SET status=?, posted_at=? WHERE id=?",
                (status, posted_at, post_id)
            )
            conn.commit()
            if status == "rejected":
                self.increment_stat("rejected")

    def update_post_content(self, post_id: int, new_text: str):
        with self._conn() as conn:
            conn.execute("UPDATE posts SET text=? WHERE id=?", (new_text, post_id))
            conn.commit()

    # ─── STATS ───────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM stats").fetchall()
            stats = {r["key"]: r["value"] for r in rows}

        # Live counts
        with self._conn() as conn:
            stats["pending"] = conn.execute(
                "SELECT COUNT(*) as c FROM posts WHERE status='pending'"
            ).fetchone()["c"]
            stats["total_pages"] = conn.execute(
                "SELECT COUNT(*) as c FROM pages WHERE active=1"
            ).fetchone()["c"]

        return stats

    def increment_stat(self, key: str, amount: int = 1):
        with self._conn() as conn:
            conn.execute(
                "UPDATE stats SET value = CAST(CAST(value AS INTEGER) + ? AS TEXT) WHERE key=?",
                (amount, key)
            )
            conn.commit()

    def set_stat(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stats (key, value) VALUES (?, ?)",
                (key, value)
            )
            conn.commit()

    def add_bandwidth_usage(self, bytes_used: int):
        kb_used = max(1, bytes_used // 1024)
        self.increment_stat("bandwidth_used_kb", kb_used)

        # Check 5GB limit warning
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM stats WHERE key='bandwidth_used_kb'"
            ).fetchone()
            if row:
                total_kb = int(row["value"])
                total_gb = total_kb / (1024 * 1024)
                if total_gb >= 4.5:
                    logger.warning(f"⚠️ Bandwidth সীমার কাছে: {total_gb:.2f} GB ব্যবহার হয়েছে!")
