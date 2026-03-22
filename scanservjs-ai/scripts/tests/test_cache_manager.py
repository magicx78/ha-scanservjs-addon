"""
Unit-Tests für HybridCache (SQLite + optional Redis)

23 Test-Cases:
- 8 SQLite-Basis Tests
- 4 Redis-Mock Tests
- Markers: @pytest.mark.unit, @pytest.mark.slow, @pytest.mark.mock
"""

import json
import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from cache_manager import HybridCache  # noqa: E402


class TestHybridCacheSQLite:
    """SQLite-Basis Tests für HybridCache."""

    @pytest.mark.unit
    def test_init_creates_database(self, mock_logger, tmp_path):
        """DB + Tabelle + Indexes werden angelegt."""
        db_path = tmp_path / "test_cache.db"
        cache = HybridCache(db_path, mock_logger)

        assert db_path.exists()
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cache_results'"
            )
            assert cursor.fetchone() is not None

            # Prüfe Indexes
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}
            assert "idx_input_hash" in indexes
            assert "idx_expires_at" in indexes

    @pytest.mark.unit
    def test_get_cache_miss(self, mock_logger, tmp_path):
        """get() auf unbekanntem Hash → None."""
        cache = HybridCache(tmp_path / "cache.db", mock_logger)
        result = cache.get("nonexistent_hash")
        assert result is None

    @pytest.mark.unit
    def test_set_and_get_sqlite(self, mock_logger, tmp_path):
        """set() + get() → result identisch."""
        cache = HybridCache(tmp_path / "cache.db", mock_logger)
        data = {"kategorie": "Lohn", "konfidenz": 0.95, "tags": ["Sparkasse"]}

        success = cache.set("hash123", data, ttl_seconds=3600)
        assert success is True

        cached = cache.get("hash123")
        assert cached is not None
        assert cached["cached"] is True
        assert cached["source"] == "sqlite"
        assert cached["result"] == data

    @pytest.mark.unit
    def test_cache_hit_increments_hits(self, mock_logger, tmp_path):
        """hits-Zähler in DB steigt nach get()."""
        db_path = tmp_path / "cache.db"
        cache = HybridCache(db_path, mock_logger)

        data = {"x": 1}
        cache.set("hash_hits", data)

        # Erste get()
        cache.get("hash_hits")
        # Zweite get()
        cache.get("hash_hits")

        # Prüfe hits in DB
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT hits FROM cache_results WHERE input_hash = ?",
                ("hash_hits",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == 2

    @pytest.mark.slow
    @pytest.mark.unit
    def test_ttl_expiry(self, mock_logger, tmp_path):
        """set(ttl=1) + sleep(2) → get() = None."""
        cache = HybridCache(tmp_path / "cache.db", mock_logger)

        cache.set("expire_hash", {"x": 1}, ttl_seconds=1)
        assert cache.get("expire_hash") is not None

        time.sleep(2)
        result = cache.get("expire_hash")
        assert result is None

    @pytest.mark.slow
    @pytest.mark.unit
    def test_cleanup_expired(self, mock_logger, tmp_path):
        """cleanup_expired() gibt korrekte Anzahl zurück."""
        db_path = tmp_path / "cache.db"
        cache = HybridCache(db_path, mock_logger)

        # Set mit kurzer TTL
        cache.set("exp1", {"x": 1}, ttl_seconds=1)
        cache.set("exp2", {"x": 2}, ttl_seconds=1)
        cache.set("keep", {"x": 3}, ttl_seconds=3600)

        time.sleep(2)

        # Cleanup sollte 2 abgelaufene Einträge löschen
        deleted = cache.cleanup_expired()
        assert deleted == 2

        # Zweiter cleanup sollte 0 löschen
        deleted_again = cache.cleanup_expired()
        assert deleted_again == 0

        # "keep" sollte noch existieren
        assert cache.get("keep") is not None

    @pytest.mark.unit
    def test_invalidate_existing(self, mock_logger, tmp_path):
        """invalidate() → danach get() = None."""
        cache = HybridCache(tmp_path / "cache.db", mock_logger)

        cache.set("to_delete", {"x": 1})
        assert cache.get("to_delete") is not None

        success = cache.invalidate("to_delete")
        assert success is True
        assert cache.get("to_delete") is None

    @pytest.mark.unit
    def test_invalidate_nonexistent(self, mock_logger, tmp_path):
        """invalidate() auf fehlendem Hash → True, kein Error."""
        cache = HybridCache(tmp_path / "cache.db", mock_logger)
        success = cache.invalidate("missing_hash")
        assert success is True


class TestHybridCacheRedis:
    """Redis-Mock Tests für HybridCache."""

    @pytest.mark.mock
    def test_redis_cache_hit(self, mock_logger, tmp_path, mock_redis_client):
        """Redis HIT → source='redis'."""
        data = {"kategorie": "Rechnung", "konfidenz": 0.88}
        redis_json = json.dumps(data)

        # Redis gibt gecachten Value zurück
        mock_redis_client.get.return_value = redis_json.encode()

        cache = HybridCache(tmp_path / "cache.db", mock_logger, redis_client=mock_redis_client)
        cached = cache.get("redis_hash")

        assert cached is not None
        assert cached["cached"] is True
        assert cached["source"] == "redis"
        assert cached["result"] == data
        # Redis.get() sollte aufgerufen sein
        mock_redis_client.get.assert_called_once()

    @pytest.mark.mock
    def test_redis_fallback_on_get_error(self, mock_logger, tmp_path, mock_redis_client):
        """Redis.get() wirft Exception → SQLite wird gefragt."""
        # Redis wirft bei get() einen Fehler
        mock_redis_client.get.side_effect = Exception("Redis connection error")

        cache = HybridCache(tmp_path / "cache.db", mock_logger, redis_client=mock_redis_client)

        # set() in SQLite
        data = {"x": 1}
        cache.set("fallback_hash", data)

        # get() sollte Redis-Fehler ignorieren und SQLite nutzen
        cached = cache.get("fallback_hash")
        assert cached is not None
        assert cached["source"] == "sqlite"
        assert cached["result"] == data

    @pytest.mark.mock
    def test_set_redis_error_still_saves_sqlite(
        self, mock_logger, tmp_path, mock_redis_client
    ):
        """Redis.setex() wirft Exception → SQLite trotzdem gespeichert."""
        # Redis wirft bei setex() einen Fehler
        mock_redis_client.setex.side_effect = Exception("Redis write failed")

        cache = HybridCache(tmp_path / "cache.db", mock_logger, redis_client=mock_redis_client)

        data = {"y": 2}
        success = cache.set("error_hash", data, ttl_seconds=3600)

        # set() sollte True zurückgeben (SQLite OK)
        assert success is True

        # Daten sollten in SQLite vorhanden sein
        cached = cache.get("error_hash")
        assert cached is not None
        assert cached["source"] == "sqlite"

    @pytest.mark.unit
    def test_no_redis_client(self, mock_logger, tmp_path):
        """redis_client=None → nur SQLite, kein Crash."""
        cache = HybridCache(tmp_path / "cache.db", mock_logger, redis_client=None)

        data = {"z": 3}
        success = cache.set("no_redis_hash", data)
        assert success is True

        cached = cache.get("no_redis_hash")
        assert cached is not None
        assert cached["source"] == "sqlite"
