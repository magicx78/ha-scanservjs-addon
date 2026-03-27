import json
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.rag import RAGEngine


class _OkResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        for line in self._lines:
            yield line

    def close(self):
        return None


class _FailThenSuccessClient:
    def __init__(self):
        self.calls = 0

    def stream(self, method, endpoint, json=None):
        self.calls += 1
        if self.calls == 1:
            raise httpx.RequestError("temporary network error", request=httpx.Request(method, endpoint))
        payloads = [
            json_module({"message": {"content": "Hallo "}, "done": False}),
            json_module({"message": {"content": "Welt"}, "done": True}),
        ]
        return _OkResponse(payloads)


class _HttpStatusFailureClient:
    def stream(self, method, endpoint, json=None):
        req = httpx.Request(method, endpoint)
        # Simulate a streaming response body that is not pre-read.
        resp = httpx.Response(
            500,
            request=req,
            headers={"content-type": "text/plain"},
            content=b"backend temporary failure",
        )
        raise httpx.HTTPStatusError("server error", request=req, response=resp)


def json_module(payload):
    return json.dumps(payload)


class TestRagRetry(unittest.TestCase):
    def test_retry_emits_meta_then_done(self):
        rag = RAGEngine(
            "http://127.0.0.1:11434",
            use_claude=False,
            max_retries=3,
            retry_base_seconds=0.01,
            retry_jitter_seconds=0.0,
        )
        rag._client = _FailThenSuccessClient()

        with patch("lib.rag.time.sleep") as sleep_mock:
            events = list(
                rag.answer_stream(
                    "frage",
                    [{"filename": "a", "page": 1, "text": "demo", "relevance_score": 1.0}],
                )
            )

        event_types = [e["type"] for e in events]
        self.assertIn("meta", event_types)
        self.assertIn("done", event_types)
        sleep_mock.assert_called()

    def test_http_status_error_is_reported_without_stream_text_crash(self):
        rag = RAGEngine(
            "http://127.0.0.1:11434",
            use_claude=False,
            max_retries=1,
        )
        rag._client = _HttpStatusFailureClient()
        events = list(
            rag.answer_stream(
                "frage",
                [{"filename": "a", "page": 1, "text": "demo", "relevance_score": 1.0}],
            )
        )
        self.assertTrue(events)
        self.assertEqual(events[-1]["type"], "error")
        self.assertIn("Ollama HTTP-Fehler", events[-1]["content"])


if __name__ == "__main__":
    unittest.main()
