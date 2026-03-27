"""
ChromaDB-Wrapper für persistente Dokumenten-Indexierung.

Speichert Embeddings + Metadaten in /data/chromadb.
Collection: "documents"
"""

import os
from pathlib import Path

import chromadb
from chromadb.config import Settings


class VectorDB:
    def __init__(self, persist_path: str = "/data/chromadb"):
        Path(persist_path).mkdir(parents=True, exist_ok=True)
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
                "page": chunk["page"],
                "chunk_index": chunk["chunk_index"],
                "md5": chunk["md5"],
            })
            embeds.append(emb)

        if ids:
            self._collection.upsert(
                ids=ids,
                documents=docs,
                metadatas=metas,
                embeddings=embeds,
            )

        return len(ids)

    def delete_document(self, filename: str) -> int:
        """Löscht alle Chunks eines Dokuments. Gibt Anzahl gelöschter Chunks zurück."""
        results = self._collection.get(where={"filename": filename})
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
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
                "distance": dist,
                "relevance_score": max(0.0, 1.0 - dist),
            })

        return output

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
                    "chunk_count": 0,
                }
            docs[fname]["chunk_count"] += 1

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
        return count

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
        }
