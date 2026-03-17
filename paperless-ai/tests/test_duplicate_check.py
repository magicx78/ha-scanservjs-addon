"""
TEST-04: Duplikat-Erkennung – gleiche MD5 zweimal → Tag [Duplikat], kein doppelter DB-Eintrag
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from duplicate_check import DuplicateChecker  # noqa: E402


@pytest.fixture()
def checker(tmp_path):
    logger = MagicMock()
    return DuplicateChecker(tmp_path / "test_hashes.db", logger)


class TestDuplicateCheck:
    def test_new_document_is_not_duplicate(self, checker):
        """Erstes Dokument ist kein Duplikat."""
        is_dup, original = checker.is_duplicate("abc123")
        assert is_dup is False
        assert original is None

    def test_registered_document_detected_as_duplicate(self, checker):
        """Gleiches MD5 zweimal → zweites Mal als Duplikat erkannt."""
        checker.register_document("abc123", "rechnung.pdf", "42")

        is_dup, original = checker.is_duplicate("abc123")
        assert is_dup is True
        assert original == "rechnung.pdf"

    def test_insert_or_ignore_prevents_duplicate_db_entry(self, checker):
        """Gleicher Hash zweimal registrieren → kein DB-Fehler, nur ein Eintrag."""
        checker.register_document("aabb", "dok.pdf", "1")
        checker.register_document("aabb", "dok.pdf", "1")  # darf nicht crashen

        # Datenbankinhalt prüfen
        import sqlite3
        with sqlite3.connect(checker.db_path) as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM document_hashes WHERE md5_hash = 'aabb'"
            ).fetchone()
        assert rows[0] == 1

    def test_different_hashes_not_duplicate(self, checker):
        """Verschiedene Hashes → kein Duplikat."""
        checker.register_document("hash1", "file1.pdf", "1")
        checker.register_document("hash2", "file2.pdf", "2")

        is_dup, _ = checker.is_duplicate("hash1")
        assert is_dup is True

        is_dup2, _ = checker.is_duplicate("hash3")
        assert is_dup2 is False

    def test_wal_mode_is_active(self, checker):
        """SQLite WAL-Mode muss aktiv sein."""
        import sqlite3
        with sqlite3.connect(checker.db_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_calculate_md5(self, tmp_path):
        """MD5-Berechnung gibt korrekten Hash zurück."""
        test_file = tmp_path / "sample.txt"
        test_file.write_bytes(b"hello world")

        result = DuplicateChecker.calculate_md5(test_file)
        assert result == "5eb63bbbe01eeed093cb22bb8f5acdc3"
