"""
Hybrid Cache Manager für Claude-Klassifikationen

SQLite als Basis, optional Redis für verteilte Caches.
Verwenden: HybridCache(db_path, redis_client)
"""

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional


class HybridCache:
    """SQLite + optional Redis Cache für Klassifikationen."""

    def __init__(self, db_path: Path, logger: logging.Logger, redis_client=None) -> None:
        """
        Args:
            db_path: Pfad zur SQLite Cache-DB
            logger: Logging-Instance
            redis_client: Optional redis.Redis Client (falls vorhanden)
        """
        self.db_path = db_path
        self.logger = logger
        self.redis = redis_client
        self._init_db()

    # -----------------------------------------------------------------------
    # Initialisierung
    # -----------------------------------------------------------------------

    def _init_db(self) -> None:
        """Erstellt Cache-Tabelle falls nicht vorhanden."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cache_results (
                        id          INTEGER  PRIMARY KEY AUTOINCREMENT,
                        input_hash  TEXT     UNIQUE NOT NULL,
                        result_json TEXT     NOT NULL,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at  TIMESTAMP,
                        hits        INTEGER  DEFAULT 0
                    )
                    """
                )
                # Index für schnelle Lookups
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_input_hash ON cache_results(input_hash)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_expires_at ON cache_results(expires_at)"
                )
            self.logger.debug(f"Cache-DB bereit: {self.db_path}")
        except sqlite3.Error as exc:
            self.logger.error(f"Konnte Cache-DB nicht initialisieren: {exc}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def get(self, input_hash: str) -> Optional[dict]:
        """
        Holt Cached Result (Redis → SQLite).

        Returns:
            dict mit 'result' + 'cached' Flag, oder None wenn abgelaufen/nicht vorhanden
        """
        # Redis (falls verfügbar und schneller)
        if self.redis:
            try:
                cached = self.redis.get(f"cache:{input_hash}")
                if cached:
                    result = json.loads(cached)
                    self.logger.debug(f"Cache HIT (Redis): {input_hash[:8]}...")
                    return {"result": result, "cached": True, "source": "redis"}
            except Exception as exc:
                self.logger.debug(f"Redis GET Fehler: {exc}")

        # SQLite Fallback
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT result_json, expires_at FROM cache_results "
                    "WHERE input_hash = ?",
                    (input_hash,),
                ).fetchone()

            if row:
                # Prüfe ob abgelaufen
                if row["expires_at"] and time.time() > row["expires_at"]:
                    self.logger.debug(f"Cache EXPIRED: {input_hash[:8]}...")
                    self._delete_sqlite(input_hash)
                    return None

                result = json.loads(row["result_json"])
                self._increment_hits_sqlite(input_hash)
                self.logger.debug(f"Cache HIT (SQLite): {input_hash[:8]}...")
                return {"result": result, "cached": True, "source": "sqlite"}

        except sqlite3.Error as exc:
            self.logger.warning(f"SQLite GET Fehler: {exc}")

        return None

    def set(self, input_hash: str, result: dict, ttl_seconds: int = 86400) -> bool:
        """
        Speichert Cached Result (SQLite + optional Redis).

        Args:
            input_hash: Hash des Inputs (z.B. MD5 von OCR-Text)
            result: Klassifikations-Result (dict)
            ttl_seconds: Cache-Gültigkeitsdauer (default: 24h)
        """
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        result_json = json.dumps(result, ensure_ascii=False)

        # SQLite
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache_results "
                    "(input_hash, result_json, expires_at, hits) VALUES (?, ?, ?, 0)",
                    (input_hash, result_json, expires_at),
                )
            self.logger.debug(f"Cache SET (SQLite): {input_hash[:8]}... TTL={ttl_seconds}s")
        except sqlite3.Error as exc:
            self.logger.error(f"SQLite SET Fehler: {exc}")
            return False

        # Redis (optional)
        if self.redis and ttl_seconds:
            try:
                self.redis.setex(
                    f"cache:{input_hash}",
                    ttl_seconds,
                    result_json,
                )
                self.logger.debug(f"Cache SET (Redis): {input_hash[:8]}...")
            except Exception as exc:
                self.logger.warning(f"Redis SET Fehler: {exc}")

        return True

    def invalidate(self, input_hash: str) -> bool:
        """Entfernt einen Cache-Entry."""
        try:
            # Redis
            if self.redis:
                try:
                    self.redis.delete(f"cache:{input_hash}")
                except Exception:
                    pass

            # SQLite
            self._delete_sqlite(input_hash)
            self.logger.debug(f"Cache INVALIDATED: {input_hash[:8]}...")
            return True
        except Exception as exc:
            self.logger.error(f"Cache INVALIDATE Fehler: {exc}")
            return False

    def cleanup_expired(self) -> int:
        """Löscht abgelaufene Einträge. Gibt Anzahl gelöschter Einträge zurück."""
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM cache_results WHERE expires_at IS NOT NULL AND expires_at < ?",
                    (time.time(),),
                )
            count = cursor.rowcount
            if count:
                self.logger.info(f"Cache CLEANUP: {count} abgelaufene Einträge gelöscht")
            return count
        except sqlite3.Error as exc:
            self.logger.error(f"Cache CLEANUP Fehler: {exc}")
            return 0

    # -----------------------------------------------------------------------
    # Interne Helfer
    # -----------------------------------------------------------------------

    def _delete_sqlite(self, input_hash: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM cache_results WHERE input_hash = ?", (input_hash,))
        except sqlite3.Error:
            pass

    def _increment_hits_sqlite(self, input_hash: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE cache_results SET hits = hits + 1 WHERE input_hash = ?",
                    (input_hash,),
                )
        except sqlite3.Error:
            pass
