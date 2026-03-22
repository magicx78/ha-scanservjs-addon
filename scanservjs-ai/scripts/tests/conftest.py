"""pytest Configuration und Fixtures für KI-Module Tests."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_logger():
    """Mock-Logger für Tests."""
    logger = MagicMock(spec=logging.Logger)
    return logger


@pytest.fixture
def sample_ocr_text():
    """Sample OCR-Text für Classification-Tests."""
    return """
    Firma: Bauhaus
    Lohnabrechnung für Christian Wiesbrock
    Januar 2024
    Bruttolohn: 3500 EUR
    Steuern: 800 EUR
    Netto: 2700 EUR

    Dies ist eine Lohnabrechnung.
    """


@pytest.fixture
def mock_claude_response():
    """Mock Claude API Response für classification."""
    return {
        "tags": ["Bauhaus", "Lohn", "2024"],
        "person": "Christian-Wiesbrock",
        "firma": "Bauhaus",
        "kategorie": "Lohn",
        "beschreibung": "Lohnabrechnung-Januar",
        "datum": "2024-01-31",
        "konfidenz": 0.95,
    }


@pytest.fixture
def mock_paperless_response():
    """Mock Paperless API Response für update_document."""
    return {
        "id": 123,
        "title": "2024-01-31_Lohn_Lohnabrechnung-Januar_[Bauhaus][Lohn][2024]",
        "document_type": 5,
        "correspondent": 10,
        "tags": [1, 2, 3],
        "created": "2024-01-31",
    }


@pytest.fixture
def mock_duplicate_entry():
    """Mock-Eintrag für Duplicate-Checker Test."""
    return {
        "md5": "abc123def456",
        "filename": "Lohnabrechnung_2024-01.pdf",
        "doc_id": 42,
    }


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporäre SQLite-DB für Duplicate-Checker Tests."""
    return tmp_path / "test_hashes.db"


@pytest.fixture
def mock_config():
    """Mock-Konfiguration für KI-Module."""
    return {
        "anthropic_api_key": "sk-test-key-12345",
        "paperless_url": "http://paperless:8000",
        "paperless_token": "test-token-12345",
        "claude_access_type": "api_key",
        "ocr_lang": "deu+eng",
        "min_konfidenz": 0.7,
    }


@pytest.fixture
def mock_requests_session():
    """Mock requests.Session für HTTP-Tests."""
    session = MagicMock()
    session.headers = {}
    session.get = MagicMock()
    session.post = MagicMock()
    return session
