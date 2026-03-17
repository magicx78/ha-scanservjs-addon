"""
MD5-Hash-basierte Duplikat-Erkennung mit SQLite-Datenbank

Datenbank wird beim ersten Aufruf automatisch angelegt.
Pfad: /config/scripts/document_hashes.db
"""

import hashlib
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Tuple


class DuplicateChecker:
    def __init__(self, db_path: Path, logger: logging.Logger) -> None:
        self.db_path = db_path
        self.logger = logger
        self._init_db()

    # -----------------------------------------------------------------------
    # Initialisierung
    # -----------------------------------------------------------------------

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS document_hashes (
                        id          INTEGER  PRIMARY KEY AUTOINCREMENT,
                        md5_hash    TEXT     UNIQUE NOT NULL,
                        filename    TEXT     NOT NULL,
                        doc_id      TEXT,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            self.logger.debug(f"Hash-Datenbank bereit: {self.db_path}")
        except sqlite3.Error as exc:
            self.logger.error(f"Konnte Hash-Datenbank nicht initialisieren: {exc}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -----------------------------------------------------------------------
    # Oeffentliche API
    # -----------------------------------------------------------------------

    @staticmethod
    def calculate_md5(filepath: Path) -> str:
        """Berechnet den MD5-Hash einer Datei (blockweise, speicherschonend)."""
        hasher = hashlib.md5()
        with open(filepath, "rb") as fh:
            for chunk in iter(lambda: fh.read(65_536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def is_duplicate(self, md5_hash: str) -> Tuple[bool, Optional[str]]:
        """Prueft ob der Hash bereits in der Datenbank liegt.

        Returns:
            (True, original_filename)  wenn Duplikat gefunden
            (False, None)              sonst
        """
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT filename FROM document_hashes WHERE md5_hash = ?",
                    (md5_hash,),
                ).fetchone()
            if row:
                return True, row[0]
            return False, None
        except sqlite3.Error as exc:
            self.logger.error(f"Datenbank-Fehler bei Duplikatpruefung: {exc}")
            # Im Zweifelsfall kein Duplikat melden (sicherer Fallback)
            return False, None

    def register_document(self, md5_hash: str, filename: str, doc_id: str) -> bool:
        """Registriert ein Dokument in der Hash-Datenbank.

        INSERT OR IGNORE verhindert doppelte Eintraege stille.
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO document_hashes "
                    "(md5_hash, filename, doc_id) VALUES (?, ?, ?)",
                    (md5_hash, filename, doc_id),
                )
            self.logger.debug(f"Hash registriert: {md5_hash[:8]}... fuer {filename!r}")
            return True
        except sqlite3.Error as exc:
            self.logger.error(f"Datenbank-Fehler beim Registrieren von {filename!r}: {exc}")
            return False
