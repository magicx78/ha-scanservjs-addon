"""
TEST-03: Claude API liefert APIStatusError 429 → FALLBACK_RESULT wird zurückgegeben
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import anthropic  # noqa: E402
from claude_namer import ClaudeNamer, FALLBACK_RESULT  # noqa: E402


@pytest.fixture()
def namer():
    cfg = {"anthropic_api_key": "sk-ant-test"}
    logger = MagicMock()
    n = ClaudeNamer(cfg, logger)
    return n


class TestClaudeLimit:
    def test_429_returns_fallback(self, namer):
        """HTTP 429 (RateLimitError) → classify() gibt FALLBACK_RESULT zurück."""
        exc = anthropic.RateLimitError(
            message="rate limit exceeded",
            response=MagicMock(status_code=429, headers={}),
            body={"error": {"type": "rate_limit_error"}},
        )
        with patch.object(namer.client.messages, "create", side_effect=exc):
            result = namer.classify("Testdokument")

        assert result["kategorie"] == FALLBACK_RESULT["kategorie"]
        assert result["konfidenz"] == 0.0
        assert "Pruefen" in result["tags"]

    def test_timeout_returns_fallback(self, namer):
        """API Timeout → classify() gibt FALLBACK_RESULT zurück."""
        exc = anthropic.APITimeoutError(request=MagicMock())
        with patch.object(namer.client.messages, "create", side_effect=exc):
            result = namer.classify("Irgendein Text")

        assert result["datum"] == FALLBACK_RESULT["datum"]
        assert result["konfidenz"] == 0.0

    def test_invalid_json_falls_back_after_retry(self, namer):
        """Ungültiges JSON zweimal → None → FALLBACK_RESULT."""
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="kein json hier")]

        with patch.object(namer.client.messages, "create", return_value=mock_msg):
            result = namer.classify("Text")

        assert result["kategorie"] == "Sonstiges"

    def test_valid_tags_call_merges_correctly(self, namer):
        """Beide Calls erfolgreich → Felder korrekt zusammengeführt."""
        tags_json = '{"tags": ["Sparkasse", "2024"], "person": "Maike", "firma": null, "konfidenz": 0.9}'
        filename_json = '{"datum": "2024-01-15", "kategorie": "Lohn", "beschreibung": "Bauhaus-Abrechnung"}'

        call_count = 0

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            msg = MagicMock()
            msg.content = [MagicMock(text=tags_json if call_count == 1 else filename_json)]
            return msg

        with patch.object(namer.client.messages, "create", side_effect=fake_create):
            result = namer.classify("Lohnabrechnung Bauhaus Januar 2024")

        assert result["datum"] == "2024-01-15"
        assert result["kategorie"] == "Lohn"
        assert "Sparkasse" in result["tags"]
        assert result["person"] == "Maike"
        assert result["konfidenz"] == pytest.approx(0.9)

    def test_normalize_unknown_kategorie(self, namer):
        """Unbekannte Kategorie wird auf 'Sonstiges' normalisiert."""
        valid_json = '{"tags": [], "person": null, "firma": null, "konfidenz": 0.5}'
        bad_kategorie = '{"datum": "2024-01-01", "kategorie": "Unbekanntes-Ding", "beschreibung": "Test"}'

        call_count = 0

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            msg = MagicMock()
            msg.content = [MagicMock(text=valid_json if call_count == 1 else bad_kategorie)]
            return msg

        with patch.object(namer.client.messages, "create", side_effect=fake_create):
            result = namer.classify("irgendwas")

        assert result["kategorie"] == "Sonstiges"
