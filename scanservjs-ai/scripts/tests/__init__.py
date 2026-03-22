"""Unit-Tests für scanservjs-ai KI-Module.

Test-Coverage:
- claude_namer.py: Claude API Klassifikation
- paperless_api.py: Paperless REST API Integration
- duplicate_check.py: MD5-basierte Duplikat-Erkennung

Test-Struktur:
- conftest.py: pytest Fixtures + Mock-Konfiguration
- test_claude_namer.py: Classification-Tests
- test_paperless_api.py: API-Integration-Tests
- test_duplicate_check.py: Hash-Duplikat-Tests

Ausführung:
    pytest -v --cov=../ --cov-report=html

Ziel: >80% Code-Coverage (ohne Test-Code selbst)
"""
