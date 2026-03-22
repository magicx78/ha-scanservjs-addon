"""Tests für claude_namer.py — Claude API Klassifikation."""

import json
from unittest.mock import MagicMock, patch

import pytest


class TestClaudeNamer:
    """Test-Suite für ClaudeNamer Klasse."""

    @patch("claude_namer.anthropic.Anthropic")
    def test_classify_valid_ocr_text(
        self, mock_anthropic, mock_logger, sample_ocr_text, mock_claude_response
    ):
        """Test: Klassifikation mit gültiger OCR-Text."""
        from claude_namer import ClaudeNamer

        # Mock Claude API
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(mock_claude_response))]
        )

        # Test
        namer = ClaudeNamer({"anthropic_api_key": "test-key"}, mock_logger)
        result = namer.classify(sample_ocr_text)

        # Assertions
        assert result["kategorie"] == "Lohn"
        assert "Bauhaus" in result["tags"]
        assert result["konfidenz"] == 0.95
        assert result["person"] == "Christian-Wiesbrock"

    @patch("claude_namer.anthropic.Anthropic")
    def test_classify_invalid_json_response(
        self, mock_anthropic, mock_logger, sample_ocr_text
    ):
        """Test: Fehlerbehandlung bei ungültiger JSON-Response."""
        from claude_namer import ClaudeNamer

        # Mock Claude API mit ungültiger Response
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="INVALID JSON {")]
        )

        # Test
        namer = ClaudeNamer({"anthropic_api_key": "test-key"}, mock_logger)
        result = namer.classify(sample_ocr_text)

        # Sollte bei Fehler sicheren Default zurückgeben
        assert result is not None or result == {}

    @patch("claude_namer.anthropic.Anthropic")
    def test_classify_empty_ocr_text(self, mock_anthropic, mock_logger):
        """Test: Klassifikation mit leerem OCR-Text."""
        from claude_namer import ClaudeNamer

        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client

        # Test
        namer = ClaudeNamer({"anthropic_api_key": "test-key"}, mock_logger)
        result = namer.classify("")

        # Sollte keine API-Call machen bei leerem Text
        assert result == {} or result is None

    @patch("claude_namer.anthropic.Anthropic")
    def test_classify_timeout(self, mock_anthropic, mock_logger, sample_ocr_text):
        """Test: Timeout-Handling bei Claude API."""
        from claude_namer import ClaudeNamer

        # Mock Timeout
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = TimeoutError("API Timeout")

        # Test
        namer = ClaudeNamer({"anthropic_api_key": "test-key"}, mock_logger)
        result = namer.classify(sample_ocr_text)

        # Sollte Fehler gracefully handhaben
        assert result == {} or result is None

    @patch("claude_namer.anthropic.Anthropic")
    def test_konfidenz_extraction(
        self, mock_anthropic, mock_logger, sample_ocr_text, mock_claude_response
    ):
        """Test: Konfidenz-Wert wird korrekt extrahiert."""
        from claude_namer import ClaudeNamer

        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(mock_claude_response))]
        )

        namer = ClaudeNamer({"anthropic_api_key": "test-key"}, mock_logger)
        result = namer.classify(sample_ocr_text)

        assert result["konfidenz"] == 0.95
        assert isinstance(result["konfidenz"], float)

    @patch("claude_namer.anthropic.Anthropic")
    def test_kategorie_in_allowed_list(
        self, mock_anthropic, mock_logger, sample_ocr_text, mock_claude_response
    ):
        """Test: Kategorie ist in erlaubter Liste."""
        from claude_namer import ClaudeNamer, KATEGORIEN

        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps(mock_claude_response))]
        )

        namer = ClaudeNamer({"anthropic_api_key": "test-key"}, mock_logger)
        result = namer.classify(sample_ocr_text)

        # Kategorie muss in erlaubter Liste sein
        assert result["kategorie"] in KATEGORIEN
