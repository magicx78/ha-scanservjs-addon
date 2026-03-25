"""Tests für paperless_api.py — Paperless API Integration."""

from unittest.mock import MagicMock, patch

import pytest
import requests


class TestPaperlessAPI:
    """Test-Suite für PaperlessAPI Klasse."""

    def test_init_with_valid_config(self, mock_logger, mock_config):
        """Test: Initialisierung mit gültiger Config."""
        from paperless_api import PaperlessAPI

        api = PaperlessAPI(mock_config, mock_logger)
        assert api is not None

    def test_init_missing_url(self, mock_logger):
        """Test: KeyError bei fehlender Paperless-URL."""
        from paperless_api import PaperlessAPI

        config = {"paperless_token": "token"}
        # paperless_url ist Pflichtfeld — KeyError erwartet
        with pytest.raises(KeyError):
            PaperlessAPI(config, mock_logger)

    @patch("paperless_api.requests.Session")
    def test_update_document_success(
        self, mock_session_class, mock_logger, mock_config, mock_paperless_response
    ):
        """Test: Dokument erfolgreich aktualisieren."""
        from paperless_api import PaperlessAPI

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.patch.return_value = MagicMock(
            status_code=200, json=lambda: mock_paperless_response
        )

        api = PaperlessAPI(mock_config, mock_logger)
        result = api.update_document(
            doc_id="123",
            title="Test Title",
            tags=["Tag1", "Tag2"],
            correspondent="Firma XY",
            document_type="Lohn",
            created="2024-01-31",
        )

        # API sollte aufgerufen worden sein
        assert mock_session.patch.called

    @patch("paperless_api.requests.Session")
    def test_update_document_api_error(
        self, mock_session_class, mock_logger, mock_config
    ):
        """Test: Fehlerbehandlung bei API-Fehler."""
        from paperless_api import PaperlessAPI

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.patch.side_effect = requests.RequestException("API Error")

        api = PaperlessAPI(mock_config, mock_logger)
        result = api.update_document(
            doc_id="123", title="Test", tags=[], correspondent=None,
            document_type=None, created=None,
        )

        # Sollte Fehler gracefully handhaben und False zurueckgeben
        assert result is False

    @patch("paperless_api.requests.Session")
    def test_add_tag_new_tag(self, mock_session_class, mock_logger, mock_config):
        """Test: Neues Tag hinzufügen (wird erstellt)."""
        from paperless_api import PaperlessAPI

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock: Tag-Abfrage (nicht vorhanden)
        mock_session.get.return_value = MagicMock(
            status_code=200, json=lambda: {"results": []}
        )
        # Mock: Tag-Erstellung
        mock_session.post.return_value = MagicMock(
            status_code=201, json=lambda: {"id": 999, "name": "NewTag"}
        )
        # Mock: Document-Update
        mock_session.patch.return_value = MagicMock(status_code=200)

        api = PaperlessAPI(mock_config, mock_logger)
        result = api.add_tag("123", "NewTag")

        # Sollte Tag erstellen und zu Dokument hinzufügen
        assert mock_session.post.called or mock_session.patch.called

    @patch("paperless_api.requests.Session")
    def test_add_tag_existing_tag(self, mock_session_class, mock_logger, mock_config):
        """Test: Existierendes Tag hinzufügen."""
        from paperless_api import PaperlessAPI

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock: Tag-Abfrage (vorhanden)
        mock_session.get.return_value = MagicMock(
            status_code=200, json=lambda: {"results": [{"id": 42, "name": "Lohn"}]}
        )
        # Mock: Document-Update
        mock_session.patch.return_value = MagicMock(status_code=200)

        api = PaperlessAPI(mock_config, mock_logger)
        result = api.add_tag("123", "Lohn")

        # Sollte existierendes Tag verwenden
        assert mock_session.patch.called

    @patch("paperless_api.requests.Session")
    def test_get_document_content_success(
        self, mock_session_class, mock_logger, mock_config
    ):
        """Test: Dokument-Content erfolgreich abrufen."""
        from paperless_api import PaperlessAPI

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"content": "Sample OCR text from PDF"},
        )

        api = PaperlessAPI(mock_config, mock_logger)
        content = api.get_document_content("123")

        assert "OCR text" in content or content != ""

    @patch("paperless_api.requests.Session")
    def test_get_document_content_not_found(
        self, mock_session_class, mock_logger, mock_config
    ):
        """Test: Dokument nicht gefunden (404)."""
        from paperless_api import PaperlessAPI

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_resp = MagicMock(status_code=404)
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_session.get.return_value = mock_resp

        api = PaperlessAPI(mock_config, mock_logger)
        content = api.get_document_content("999")

        # raise_for_status() wirft bei 404, wird abgefangen -> leerer String
        assert content == ""

    @patch("paperless_api.requests.Session")
    def test_connection_timeout(
        self, mock_session_class, mock_logger, mock_config
    ):
        """Test: Timeout bei Verbindung zu Paperless."""
        from paperless_api import PaperlessAPI

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.get.side_effect = requests.Timeout("Connection Timeout")

        api = PaperlessAPI(mock_config, mock_logger)
        content = api.get_document_content("123")

        # Sollte Fehler gracefully handhaben
        assert mock_logger.error.called or content == ""
