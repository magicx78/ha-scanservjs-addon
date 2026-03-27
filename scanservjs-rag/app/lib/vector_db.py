"""
ChromaDB-Wrapper für persistente Dokumenten-Indexierung.

Speichert Embeddings + Metadaten in /data/chromadb.
Collection: "documents"
"""

import os
import time
from pathlib import Path

import chromadb
from chromadb.config import Settings


class VectorDB:
    def __init__(self, persist_path: str = "/data/chromadb"):
        self._persist_path = Path(persist_path)
        self._persist_path.mkdir(parents=True, exist_ok=True)
        self._revision_file = self._persist_path / ".revision"
        self._revision = self._load_revision()
        self._client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------

    def add_document(
        self,
        filename: str,
        chunks: list[dict],
        embeddings: list[list[float]],
    ) -> int:
        """Fügt Chunks eines Dokuments in die Datenbank ein.

        Gibt Anzahl der tatsächlich hinzugefügten Chunks zurück.
        Überspringt leere Embeddings.
        """
        ids, docs, metas, embeds = [], [], [], []

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            if not emb:
                continue
            chunk_id = f"{filename}::p{chunk['page']}::c{chunk['chunk_index']}"
            ids.append(chunk_id)
            docs.append(chunk["text"])
            metas.append({
                "filename": chunk["filename"],
                "source": chunk["source"],
                "source_label": chunk.get("source_label", "unknown"),
                "page": chunk["page"],
                "chunk_index": chunk["chunk_index"],
                "md5": chunk["md5"],
                "updated_at": int(time.time()),
            })
            embeds.append(emb)

        if ids:
            self._collection.upsert(
                ids=ids,
                documents=docs,
                metadatas=metas,
                embeddings=embeds,
            )
            self._bump_revision()

        return len(ids)

    def delete_document(self, filename: str) -> int:
        """Löscht alle Chunks eines Dokuments. Gibt Anzahl gelöschter Chunks zurück."""
        results = self._collection.get(where={"filename": filename})
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
            self._bump_revision()
        return len(ids)

    # ------------------------------------------------------------------
    # Lesen / Suchen
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        filename_filter: str | None = None,
    ) -> list[dict]:
        """Semantische Suche. Gibt sortierte Liste von Ergebnis-Dicts zurück.

        Jedes Dict: {text, filename, page, source, distance, relevance_score}
        """
        if not query_embedding:
            return []

        where = {"filename": filename_filter} if filename_filter else None
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, max(1, self._collection.count())),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        try:
            results = self._collection.query(**kwargs)
        except Exception:
            return []

        output = []
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            output.append({
                "text": doc,
                "filename": meta.get("filename", ""),
                "page": meta.get("page", 1),
                "source": meta.get("source", ""),
                "source_label": meta.get("source_label", "unknown"),
                "distance": dist,
                "relevance_score": max(0.0, 1.0 - dist),
            })

        return output

    def search_progressive(
        self,
        query_embedding: list[float],
        steps: list[int],
        filename_filter: str | None = None,
    ):
        """Progressive semantische Suche in Stufen.

        Liefert pro Stufe ein Dict:
        {
            "step": int,
            "limit": int,
            "results": list[dict],       # kumulierte deduplizierte Treffer
            "new_results": list[dict],   # nur neu hinzugekommene Treffer in dieser Stufe
        }
        """
        if not query_embedding:
            return

        max_count = max(1, self._collection.count())
        normalized_steps = []
        for step in steps:
            if step and step > 0:
                normalized_steps.append(min(step, max_count))
        if not normalized_steps:
            normalized_steps = [min(5, max_count)]

        # Reihenfolge beibehalten, doppelte Step-Limits entfernen
        seen_limits = set()
        deduped_steps = []
        for limit in normalized_steps:
            if limit in seen_limits:
                continue
            seen_limits.add(limit)
            deduped_steps.append(limit)

        cumulative = []
        seen_keys: set[tuple] = set()

        for idx, limit in enumerate(deduped_steps, start=1):
            try:
                raw = self.search(
                    query_embedding=query_embedding,
                    n_results=limit,
                    filename_filter=filename_filter,
                )
                error = ""
            except Exception as exc:  # defensive, search() already catches most cases
                raw = []
                error = str(exc)

            newly_added = []
            for item in raw:
                key = (
                    item.get("filename", ""),
                    item.get("page", 1),
                    item.get("source", ""),
                    item.get("text", "")[:160],
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                cumulative.append(item)
                newly_added.append(item)

            yield {
                "step": idx,
                "limit": limit,
                "results": list(cumulative),
                "new_results": newly_added,
                "error": error,
            }

    def is_indexed(self, md5: str) -> bool:
        """Prüft ob ein Dokument (per MD5) bereits indexiert wurde."""
        try:
            results = self._collection.get(where={"md5": md5}, limit=1)
            return len(results.get("ids", [])) > 0
        except Exception:
            return False

    def list_documents(self) -> list[dict]:
        """Gibt alle indizierten Dokumente zurück (dedupliziert nach Dateiname).

        Format: [{filename, source, chunk_count}]
        """
        try:
            results = self._collection.get(include=["metadatas"])
        except Exception:
            return []

        docs: dict[str, dict] = {}
        for meta in results.get("metadatas", []):
            fname = meta.get("filename", "")
            if fname not in docs:
                docs[fname] = {
                    "filename": fname,
                    "source": meta.get("source", ""),
                    "source_label": meta.get("source_label", "unknown"),
                    "chunk_count": 0,
                    "updated_at": meta.get("updated_at", 0),
                }
            docs[fname]["chunk_count"] += 1
            docs[fname]["updated_at"] = max(
                int(docs[fname].get("updated_at", 0)),
                int(meta.get("updated_at", 0)),
            )

        return sorted(docs.values(), key=lambda d: d["filename"])

    # ------------------------------------------------------------------
    # Statistiken
    # ------------------------------------------------------------------

    def reset(self) -> int:
        """Löscht alle Dokumente. Gibt Anzahl gelöschter Chunks zurück."""
        count = self._collection.count()
        self._client.delete_collection("documents")
        self._collection = self._client.get_or_create_collection(
            name="documents",
            metadata={"hnsw:space": "cosine"},
        )
        self._bump_revision()
        return count

    def get_revision(self) -> int:
        return int(self._revision)

    def _load_revision(self) -> int:
        try:
            if self._revision_file.exists():
                return int(self._revision_file.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            pass
        return 0

    def _write_revision(self):
        tmp = self._revision_file.with_suffix(".tmp")
        tmp.write_text(str(self._revision), encoding="utf-8")
        tmp.replace(self._revision_file)

    def _bump_revision(self):
        self._revision = int(self._revision) + 1
        self._write_revision()

    def get_stats(self) -> dict:
        """Gibt Statistiken zur Datenbank zurück."""
        total_chunks = self._collection.count()
        docs = self.list_documents()
        persist_path = self._client._settings.persist_directory if hasattr(self._client, "_settings") else "/data/chromadb"

        # Speicherverbrauch berechnen
        db_size_bytes = 0
        try:
            for root, _, files in os.walk(persist_path):
                for f in files:
                    db_size_bytes += os.path.getsize(os.path.join(root, f))
        except Exception:
            pass

        return {
            "total_documents": len(docs),
            "total_chunks": total_chunks,
            "db_size_mb": round(db_size_bytes / (1024 * 1024), 2),
            "revision": self.get_revision(),
        }
