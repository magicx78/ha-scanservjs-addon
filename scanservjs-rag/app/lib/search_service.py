"""
Search service exposing a normal and a streaming search endpoint abstraction.

This module keeps the classic one-shot `search(...)` behavior while adding
`search_stream(...)` with structured phase events for progressive rendering.
"""

from __future__ import annotations

from typing import Callable


def _dedupe_hits(hits: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    for hit in hits:
        key = (
            hit.get("filename", ""),
            int(hit.get("page", 1) or 1),
            int(hit.get("chunk_index", 0) or 0),
            hit.get("source", ""),
            (hit.get("text", "") or "")[:160],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


class SearchService:
    """Backend-like search abstraction with normal + streaming endpoints."""

    def __init__(self, db, embedder, rag, max_results: int = 5):
        self.db = db
        self.embedder = embedder
        self.rag = rag
        self.max_results = max(1, int(max_results))

    def search(self, query: str, cancel_check: Callable[[], bool] | None = None) -> dict:
        """Normal endpoint: returns final payload in one response."""
        final_hits: list[dict] = []
        final_answer = ""
        status_message = "Suche abgeschlossen."

        for event in self.search_stream(query, cancel_check=cancel_check):
            etype = event.get("type")
            if etype == "partial_results":
                final_hits = list(event.get("partialResults", final_hits))
                status_message = event.get("statusMessage", status_message)
            elif etype == "generating_answer":
                final_answer = event.get("answer", final_answer)
                status_message = event.get("statusMessage", status_message)
            elif etype == "done":
                final_hits = list(event.get("hits", final_hits))
                final_answer = event.get("answer", final_answer)
                status_message = event.get("statusMessage", status_message)
                return {
                    "hits": final_hits,
                    "answer": final_answer,
                    "statusMessage": status_message,
                }
            elif etype == "error":
                raise RuntimeError(event.get("message", "Unbekannter Suchfehler."))

        return {
            "hits": final_hits,
            "answer": final_answer,
            "statusMessage": status_message,
        }

    def search_stream(self, query: str, cancel_check: Callable[[], bool] | None = None):
        """Streaming endpoint with structured phase events.

        Event types:
        - started
        - retrieving
        - reranking
        - partial_results
        - generating_answer
        - done
        - error
        """
        query = (query or "").strip()
        if not query:
            yield {"type": "error", "message": "Leere Suchanfrage."}
            return

        if callable(cancel_check) and cancel_check():
            yield {"type": "error", "message": "Anfrage wurde vor Start abgebrochen."}
            return

        yield {"type": "started", "statusMessage": "Suche gestartet."}
        yield {"type": "retrieving", "statusMessage": "Treffer werden geladen..."}

        query_embedding = self.embedder.embed(query)
        if not query_embedding:
            yield {"type": "error", "message": "Embedding fehlgeschlagen. Ist Ollama erreichbar?"}
            return

        partial_hits: list[dict] = []
        steps = sorted({1, min(3, self.max_results), self.max_results})
        for payload in self.db.search_progressive(query_embedding=query_embedding, steps=steps):
            if callable(cancel_check) and cancel_check():
                yield {"type": "error", "message": "Anfrage wurde waehrend der Suche abgebrochen."}
                return

            payload_error = payload.get("error")
            if payload_error:
                yield {
                    "type": "retrieving",
                    "statusMessage": f"Teilweise Suchwarnung: {payload_error[:180]}",
                }

            current = _dedupe_hits(list(payload.get("results", [])))
            if not current:
                continue
            partial_hits = current
            yield {
                "type": "partial_results",
                "partialResults": list(partial_hits),
                "statusMessage": f"{len(partial_hits)} Treffer gefunden (Stufe {payload.get('step', 1)}/{len(steps)}).",
                "step": int(payload.get("step", 1) or 1),
                "totalSteps": len(steps),
            }

        if callable(cancel_check) and cancel_check():
            yield {"type": "error", "message": "Anfrage wurde abgebrochen."}
            return

        yield {"type": "reranking", "statusMessage": "Treffer werden final sortiert..."}

        final_hits = _dedupe_hits(
            self.db.search(query_embedding=query_embedding, n_results=self.max_results)
        )
        if final_hits:
            yield {
                "type": "partial_results",
                "partialResults": list(final_hits),
                "statusMessage": f"{len(final_hits)} Treffer nach Relevanz sortiert.",
                "step": len(steps),
                "totalSteps": len(steps),
            }
        else:
            yield {
                "type": "done",
                "hits": [],
                "answer": "Keine relevanten Treffer gefunden.",
                "statusMessage": "Keine Treffer gefunden.",
            }
            return

        yield {"type": "generating_answer", "statusMessage": "Antwort wird aufgebaut...", "answer": ""}

        answer_text = ""
        for event in self.rag.answer_stream(
            query,
            final_hits,
            mode="initial",
            cancel_check=cancel_check,
        ):
            if callable(cancel_check) and cancel_check():
                yield {"type": "error", "message": "Anfrage wurde waehrend der Antwortgenerierung abgebrochen."}
                return

            ev_type = event.get("type")
            if ev_type == "token":
                token = event.get("content", "")
                answer_text += token
                yield {
                    "type": "generating_answer",
                    "statusMessage": "Antwort wird generiert...",
                    "answerDelta": token,
                    "answer": answer_text,
                }
            elif ev_type == "meta":
                yield {
                    "type": "generating_answer",
                    "statusMessage": event.get("content", "Antwort wird generiert..."),
                    "answer": answer_text,
                }
            elif ev_type == "done":
                answer_text = event.get("content", answer_text) or answer_text
                break
            elif ev_type == "cancelled":
                yield {"type": "error", "message": event.get("content", "Anfrage abgebrochen.")}
                return
            elif ev_type == "error":
                yield {"type": "error", "message": event.get("content", "Antwortgenerierung fehlgeschlagen.")}
                return

        yield {
            "type": "done",
            "hits": list(final_hits),
            "answer": answer_text or "Keine Antwort erhalten.",
            "statusMessage": "Suche abgeschlossen.",
        }

