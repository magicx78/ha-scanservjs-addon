import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.rag import RAGEngine


class TestRagCancellation(unittest.TestCase):
    def test_cancelled_before_stream(self):
        rag = RAGEngine("http://127.0.0.1:1", llm_model="qwen2.5:14b", use_claude=False)
        events = list(
            rag.answer_stream(
                "frage",
                [{"filename": "a", "page": 1, "text": "demo", "relevance_score": 1.0}],
                cancel_check=lambda: True,
            )
        )
        self.assertTrue(events)
        self.assertEqual(events[0]["type"], "cancelled")


if __name__ == "__main__":
    unittest.main()
