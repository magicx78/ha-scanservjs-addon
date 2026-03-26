"""
Watch-Folder: Überwacht einen Ordner auf neue Dokumente und indexiert sie automatisch.

Nutzt watchdog für Filesystem-Events.
Wird als Background-Thread in Streamlit gestartet.
"""

import logging
import os
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from watchdog.observers import Observer

from lib.chunker import DocumentChunker, SUPPORTED_EXTENSIONS, calculate_md5
from lib.embedder import OllamaEmbedder
from lib.vector_db import VectorDB

logger = logging.getLogger("watcher")


class _DocumentHandler(FileSystemEventHandler):
    def __init__(
        self,
        db: VectorDB,
        embedder: OllamaEmbedder,
        chunker: DocumentChunker,
        on_indexed: callable = None,
    ):
        self._db = db
        self._embedder = embedder
        self._chunker = chunker
        self._on_indexed = on_indexed
        self._processing: set[str] = set()
        self._lock = threading.Lock()

    def _should_process(self, path: str) -> bool:
        suffix = Path(path).suffix.lower()
        return suffix in SUPPORTED_EXTENSIONS

    def _wait_for_file(self, path: str, timeout: int = 30) -> bool:
        """Wartet bis Datei vollständig geschrieben wurde."""
        deadline = time.time() + timeout
        last_size = -1
        while time.time() < deadline:
            try:
                size = os.path.getsize(path)
                if size == last_size and size > 0:
                    return True
                last_size = size
                time.sleep(0.5)
            except OSError:
                time.sleep(0.5)
        return False

    def _index_file(self, path: str):
        with self._lock:
            if path in self._processing:
                return
            self._processing.add(path)

        try:
            file_path = Path(path)
            if not file_path.exists():
                return

            # Warten bis Datei stabil ist
            if not self._wait_for_file(path):
                logger.warning(f"Datei-Timeout: {path}")
                return

            # Duplikat-Check
            md5 = calculate_md5(file_path)
            if self._db.is_indexed(md5):
                logger.info(f"Bereits indexiert (MD5): {file_path.name}")
                return

            logger.info(f"Indexiere: {file_path.name}")

            # Chunken
            chunks = self._chunker.chunk_file(file_path)
            if not chunks:
                logger.warning(f"Keine Chunks extrahiert: {file_path.name}")
                return

            # Einbetten
            embeddings = [self._embedder.embed(c["text"]) for c in chunks]

            # Speichern
            added = self._db.add_document(file_path.name, chunks, embeddings)
            logger.info(f"Indexiert: {file_path.name} — {added} Chunks")

            if self._on_indexed:
                self._on_indexed(file_path.name, added)

        except Exception as exc:
            logger.error(f"Fehler beim Indexieren von {path}: {exc}", exc_info=True)
        finally:
            with self._lock:
                self._processing.discard(path)

    def on_created(self, event):
        if not event.is_directory and self._should_process(event.src_path):
            threading.Thread(
                target=self._index_file,
                args=(event.src_path,),
                daemon=True,
            ).start()

    def on_moved(self, event):
        if not event.is_directory and self._should_process(event.dest_path):
            threading.Thread(
                target=self._index_file,
                args=(event.dest_path,),
                daemon=True,
            ).start()


class FolderWatcher:
    """Überwacht einen Ordner und indexiert neue Dokumente automatisch."""

    def __init__(
        self,
        watch_folder: str,
        db: VectorDB,
        embedder: OllamaEmbedder,
        ocr_lang: str = "deu+eng",
        on_indexed: callable = None,
    ):
        self._watch_folder = watch_folder
        self._db = db
        self._embedder = embedder
        self._chunker = DocumentChunker(ocr_lang=ocr_lang)
        self._on_indexed = on_indexed
        self._observer: Observer | None = None
        self._running = False

    def start(self):
        """Startet den Watcher in einem Background-Thread."""
        if self._running:
            return

        folder = Path(self._watch_folder)
        if not folder.exists():
            logger.warning(f"Watch-Ordner existiert nicht: {self._watch_folder}")
            return

        handler = _DocumentHandler(
            db=self._db,
            embedder=self._embedder,
            chunker=self._chunker,
            on_indexed=self._on_indexed,
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(folder), recursive=False)
        self._observer.start()
        self._running = True
        logger.info(f"Watch-Ordner aktiv: {self._watch_folder}")

    def stop(self):
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def index_existing(self):
        """Indexiert alle bereits vorhandenen Dateien im Watch-Ordner (Erstlauf)."""
        folder = Path(self._watch_folder)
        if not folder.exists():
            return

        for file_path in sorted(folder.iterdir()):
            if file_path.is_file() and DocumentChunker.is_supported(file_path):
                try:
                    md5 = calculate_md5(file_path)
                    if self._db.is_indexed(md5):
                        continue

                    chunks = self._chunker.chunk_file(file_path)
                    if not chunks:
                        continue

                    embeddings = [self._embedder.embed(c["text"]) for c in chunks]
                    added = self._db.add_document(file_path.name, chunks, embeddings)
                    logger.info(f"Erstlauf indexiert: {file_path.name} — {added} Chunks")

                    if self._on_indexed:
                        self._on_indexed(file_path.name, added)

                except Exception as exc:
                    logger.error(f"Erstlauf Fehler {file_path.name}: {exc}")
