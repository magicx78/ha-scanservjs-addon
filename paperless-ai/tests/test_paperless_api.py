"""
TEST-01: Paperless API – leerer Body / HTTP-500 → kein Crash
TEST-02: OCR-Text leer → Tag [Pruefen] wird gesetzt
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from paperless_api import PaperlessAPI  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def cfg():
    return {
        "paperless_url": "http://fake-paperless:8000",
        "paperless_token": "test-token-123",
    }


@pytest.fixture()
def api(cfg):
    logger = MagicMock()
    return PaperlessAPI(cfg, logger)


# ---------------------------------------------------------------------------
# TEST-01: Leerer Body / HTTP-500 → kein Crash
# ---------------------------------------------------------------------------

class TestApiFallback:
    def test_empty_body_returns_empty_string(self, api):
        """Leere Antwort (kein JSON) → get_document_content gibt '' zurück."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("No JSON")
        mock_resp.text = ""

        with patch.object(api.session, "get", return_value=mock_resp):
            result = api.get_document_content("42")

        assert result == ""
        api.logger.error.assert_called_once()

    def test_http_500_returns_empty_string(self, api):
        """HTTP 500 → get_document_content gibt '' zurück, kein Exception."""
        import requests

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

        with patch.object(api.session, "get", return_value=mock_resp):
            result = api.get_document_content("99")

        assert result == ""
        api.logger.error.assert_called_once()

    def test_connection_error_returns_empty_string(self, api):
        """Netzwerkfehler → get_document_content gibt '' zurück."""
        import requests

        with patch.object(api.session, "get", side_effect=requests.ConnectionError("timeout")):
            result = api.get_document_content("7")

        assert result == ""

    def test_get_or_create_invalid_json_returns_none(self, api):
        """_get_or_create gibt None zurück wenn JSON ungültig."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("bad JSON")

        with patch.object(api.session, "get", return_value=mock_resp):
            result = api.get_or_create_tag("TestTag")

        assert result is None

    def test_update_document_returns_false_on_error(self, api):
        """update_document gibt False zurück bei HTTP-Fehler."""
        import requests

        mock_get = MagicMock()
        mock_get.raise_for_status.return_value = None
        mock_get.json.return_value = {"results": [{"id": 1}]}

        mock_patch = MagicMock()
        mock_patch.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        mock_patch.text = "title too long"

        with patch.object(api.session, "get", return_value=mock_get), \
             patch.object(api.session, "patch", return_value=mock_patch):
            result = api.update_document(
                doc_id="5",
                title="Test",
                correspondent=None,
                document_type=None,
                tags=[],
                created=None,
            )

        assert result is False


# ---------------------------------------------------------------------------
# TEST-02: OCR-Text leer → Tag [Pruefen] wird gesetzt
# ---------------------------------------------------------------------------

class TestOcrMissing:
    def test_empty_content_returns_empty_string(self, api):
        """Dokument ohne content-Feld → leerer String."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"id": 1, "title": "Test"}  # kein 'content'

        with patch.object(api.session, "get", return_value=mock_resp):
            result = api.get_document_content("1")

        assert result == ""

    def test_null_content_returns_empty_string(self, api):
        """content=null → leerer String."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"id": 1, "content": None}

        with patch.object(api.session, "get", return_value=mock_resp):
            result = api.get_document_content("1")

        assert result == ""

    def test_add_pruefen_tag_on_empty_ocr(self, api):
        """add_tag('Pruefen') muss erfolgreich funktionieren."""
        mock_get = MagicMock()
        mock_get.raise_for_status.return_value = None
        mock_get.json.side_effect = [
            {"tags": []},                   # Erster GET: aktuelle Tags
            {"results": []},                # GET tags/ → nicht gefunden
        ]

        mock_post = MagicMock()
        mock_post.raise_for_status.return_value = None
        mock_post.json.return_value = {"id": 99, "name": "Pruefen"}

        mock_patch = MagicMock()
        mock_patch.raise_for_status.return_value = None

        with patch.object(api.session, "get", return_value=mock_get), \
             patch.object(api.session, "post", return_value=mock_post), \
             patch.object(api.session, "patch", return_value=mock_patch):
            result = api.add_tag("42", "Pruefen")

        assert result is True
