"""
Persistent search cache with TTL and bounded size.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path


class PersistentSearchCache:
    def __init__(self, db_path: str, ttl_seconds: int = 180, max_entries: int = 200):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl_seconds = int(max(1, ttl_seconds))
        self._max_entries = int(max(10, max_entries))
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_cache (
                    key_hash TEXT PRIMARY KEY,
                    key_text TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    stored_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    last_access REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_cache(expires_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_search_cache_last_access ON search_cache(last_access)"
            )

    @staticmethod
    def hash_key(key_text: str) -> str:
        return hashlib.sha256(key_text.encode("utf-8")).hexdigest()

    def get(self, key_text: str) -> dict | None:
        now = time.time()
        key_hash = self.hash_key(key_text)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, expires_at FROM search_cache WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if not row:
                return None
            if float(row["expires_at"]) <= now:
                conn.execute("DELETE FROM search_cache WHERE key_hash = ?", (key_hash,))
                return None
            conn.execute(
                "UPDATE search_cache SET last_access = ? WHERE key_hash = ?",
                (now, key_hash),
            )
            try:
                return json.loads(row["payload_json"])
            except Exception:
                conn.execute("DELETE FROM search_cache WHERE key_hash = ?", (key_hash,))
                return None

    def set(self, key_text: str, payload: dict):
        now = time.time()
        expires_at = now + self._ttl_seconds
        key_hash = self.hash_key(key_text)
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO search_cache (key_hash, key_text, payload_json, stored_at, expires_at, last_access)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key_hash) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    stored_at = excluded.stored_at,
                    expires_at = excluded.expires_at,
                    last_access = excluded.last_access,
                    key_text = excluded.key_text
                """,
                (key_hash, key_text, payload_json, now, expires_at, now),
            )
            self._prune_locked(conn, now)

    def invalidate_all(self):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM search_cache")

    def _prune_locked(self, conn, now: float):
        conn.execute("DELETE FROM search_cache WHERE expires_at <= ?", (now,))
        count_row = conn.execute("SELECT COUNT(*) AS c FROM search_cache").fetchone()
        count = int(count_row["c"]) if count_row else 0
        if count <= self._max_entries:
            return
        overflow = count - self._max_entries
        conn.execute(
            """
            DELETE FROM search_cache
            WHERE key_hash IN (
              SELECT key_hash FROM search_cache
              ORDER BY last_access ASC
              LIMIT ?
            )
            """,
            (overflow,),
        )
