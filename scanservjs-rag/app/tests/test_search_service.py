import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.search_service import SearchService


class _FakeEmbedder:
    def embed(self, query: str):
        if "no-embed" in query:
            return []
        return [0.1, 0.2]


class _FakeDB:
    def search_progressive(self, query_embedding, steps):
        yield {
            "step": 1,
            "limit": 1,
            "results": [
                {
                    "filename": "doc1.pdf",
                    "page": 1,
                    "chunk_index": 0,
                    "source": "/tmp/doc1.pdf",
                    "source_label": "upload",
                    "text": "erste info",
                    "relevance_score": 0.92,
                }
            ],
            "new_results": [],
            "error": "",
        }

    def search(self, query_embedding, n_results=5):
        return [
            {
                "filename": "doc1.pdf",
                "page": 1,
                "chunk_index": 0,
                "source": "/tmp/doc1.pdf",
                "source_label": "upload",
                "text": "erste info",
                "relevance_score": 0.92,
            },
            {
                "filename": "doc2.pdf",
                "page": 2,
                "chunk_index": 1,
                "source": "/tmp/doc2.pdf",
                "source_label": "paperless",
                "text": "zweite info",
                "relevance_score": 0.88,
            },
        ]


class _FakeRAG:
    def answer_stream(self, query, hits, mode="initial", cancel_check=None):
        if callable(cancel_check) and cancel_check():
            yield {"type": "cancelled", "content": "abgebrochen"}
            return
        yield {"type": "token", "content": "Teil "}
        yield {"type": "token", "content": "Antwort"}
        yield {"type": "done", "content": "Teil Antwort"}


class _EmptyDB(_FakeDB):
    def search_progressive(self, query_embedding, steps):
        yield {"step": 1, "limit": 1, "results": [], "new_results": [], "error": ""}

    def search(self, query_embedding, n_results=5):
        return []


class TestSearchService(unittest.TestCase):
    def test_stream_emits_expected_phases(self):
        service = SearchService(db=_FakeDB(), embedder=_FakeEmbedder(), rag=_FakeRAG(), max_results=5)
        events = list(service.search_stream("rechnung 2024"))
        types = [e.get("type") for e in events]
        self.assertIn("started", types)
        self.assertIn("retrieving", types)
        self.assertIn("reranking", types)
        self.assertIn("partial_results", types)
        self.assertIn("generating_answer", types)
        self.assertIn("done", types)
        self.assertNotIn("error", types)

    def test_normal_search_endpoint_returns_final_payload(self):
        service = SearchService(db=_FakeDB(), embedder=_FakeEmbedder(), rag=_FakeRAG(), max_results=5)
        result = service.search("vertrag")
        self.assertEqual(len(result["hits"]), 2)
        self.assertIn("Antwort", result["answer"])
        self.assertIn("abgeschlossen", result["statusMessage"].lower())

    def test_empty_result_path(self):
        service = SearchService(db=_EmptyDB(), embedder=_FakeEmbedder(), rag=_FakeRAG(), max_results=5)
        events = list(service.search_stream("leer"))
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["hits"], [])


if __name__ == "__main__":
    unittest.main()

