# KI-Module Unit-Tests

Umfassende Test-Suite für Claude-Klassifikation, Paperless-API und Duplikat-Erkennung.

## Setup

### Installation (lokale Entwicklung)

```bash
pip install pytest pytest-cov pytest-mock pytest-timeout
```

### Docker-Integration

Tests sind in der `requirements.txt` enthalten:
```bash
docker-compose exec scanservjs-ai pytest tests/ -v --cov=../ --cov-report=html
```

## Test-Struktur

```
tests/
├── conftest.py              # pytest Fixtures (Mock-Daten, Logger, etc.)
├── test_claude_namer.py     # ClaudeNamer.classify() Tests
├── test_paperless_api.py    # PaperlessAPI Integrations-Tests
├── test_duplicate_check.py  # DuplicateChecker Hash-Tests
├── pytest.ini               # pytest Konfiguration + Coverage-Schwelle
├── .coveragerc              # Coverage-Reports
├── Makefile                 # Test-Kommando-Shortcuts
└── README.md                # Diese Datei
```

## Tests ausführen

### Alle Tests
```bash
make test
# oder:
pytest tests/ -v
```

### Verbose Output
```bash
make test-verbose
pytest tests/ -vv -s
```

### Mit Coverage-Report (>80% erforderlich)
```bash
make test-coverage
pytest tests/ -v --cov=../ --cov-report=html --cov-fail-under=80
```

### Schnelle Tests (ohne Coverage)
```bash
make test-quick
pytest tests/ -q --tb=short
```

### Nach Tag filtern
```bash
pytest tests/ -v -m unit      # Nur Unit-Tests
pytest tests/ -v -m mock      # Nur Tests mit Mocks
```

## Test-Coverage

| Modul | Tests | Coverage |
|-------|-------|----------|
| `claude_namer.py` | 6 Tests | Valid/Invalid JSON, Timeout, Konfidenz, Kategorie |
| `paperless_api.py` | 8 Tests | Update/Tag/Content, Errors, Timeout, 404 |
| `duplicate_check.py` | 9 Tests | MD5, Register, Check, Persistence, Large Files |
| **Gesamt** | **23 Tests** | **>80%** ✓ |

## Test-Details

### claude_namer.py Tests

- ✅ `test_classify_valid_ocr_text`: Klassifikation mit gültiger OCR
- ✅ `test_classify_invalid_json_response`: Fehlerbehandlung bei ungültiger JSON
- ✅ `test_classify_empty_ocr_text`: Leerer Text-Handling
- ✅ `test_classify_timeout`: API-Timeout Fehlerbehandlung
- ✅ `test_konfidenz_extraction`: Konfidenz-Wert Extraktion
- ✅ `test_kategorie_in_allowed_list`: Kategorie-Validierung

### paperless_api.py Tests

- ✅ `test_init_with_valid_config`: Initialisierung
- ✅ `test_init_missing_url`: Fehler bei fehlenden Parametern
- ✅ `test_update_document_success`: Dokument aktualisieren
- ✅ `test_update_document_api_error`: API-Fehler Handling
- ✅ `test_add_tag_new_tag`: Neues Tag erstellen und hinzufügen
- ✅ `test_add_tag_existing_tag`: Existierendes Tag verwenden
- ✅ `test_get_document_content_success`: Content abrufen
- ✅ `test_get_document_content_not_found`: 404-Handling
- ✅ `test_connection_timeout`: Timeout-Handling

### duplicate_check.py Tests

- ✅ `test_init_creates_database`: DB-Initialisierung
- ✅ `test_calculate_md5_valid_file`: MD5 für Datei
- ✅ `test_calculate_md5_invalid_file`: Fehler bei nicht-existenter Datei
- ✅ `test_register_and_check_duplicate`: Register + Check Workflow
- ✅ `test_is_not_duplicate_first_registration`: Erste Registrierung
- ✅ `test_is_duplicate_second_occurrence`: Duplikat-Erkennung
- ✅ `test_database_persistence`: DB-Persistanz
- ✅ `test_different_files_different_md5`: Hash-Eindeutigkeit
- ✅ `test_same_content_same_md5`: Hash-Konsistenz
- ✅ `test_large_file_handling`: Große Dateien

## Mocks & Fixtures (conftest.py)

| Fixture | Zweck |
|---------|-------|
| `mock_logger` | Logging-Mock für Tests |
| `sample_ocr_text` | Sample OCR-Text (Lohnabrechnung) |
| `mock_claude_response` | Mock Claude API Response |
| `mock_paperless_response` | Mock Paperless API Response |
| `mock_duplicate_entry` | Mock DB-Eintrag |
| `temp_db_path` | Temporäre Test-Datenbank |
| `mock_config` | Mock-Konfiguration |
| `mock_requests_session` | Mock requests.Session |

## CI/CD Integration

### GitHub Actions (optional)

```yaml
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - run: pip install -r requirements.txt
      - run: cd scanservjs-ai/scripts && pytest tests/ -v --cov=../ --cov-fail-under=80
```

## Debugging

### Single Test ausführen
```bash
pytest tests/test_claude_namer.py::TestClaudeNamer::test_classify_valid_ocr_text -vv -s
```

### Mit Debugging-Output
```bash
pytest tests/ -vv -s --tb=long --capture=no
```

### Bestimmter Test-Marker
```bash
pytest tests/ -v -m mock --tb=short
```

## Best Practices

1. **Mocks verwenden**: Keine echten API-Calls in Tests
2. **Fixtures**: Reuse via conftest.py
3. **Deskriptive Namen**: `test_classify_valid_ocr_text` statt `test_1`
4. **Edge Cases**: Tests für Error-Handling + Timeouts
5. **DB-Tests**: Temporäre DBs verwenden (`temp_db_path`)
6. **Coverage**: >80% anstreben, nicht 100% (Tests selbst ausschließen)

## Troubleshooting

### pytest nicht gefunden
```bash
pip install pytest pytest-cov pytest-mock pytest-timeout
```

### Coverage unter 80%
```bash
pytest tests/ --cov=../ --cov-report=term-missing
# Zeigt welche Zeilen nicht getestet sind
```

### Mock-Fehler
Stelle sicher, dass `@patch()` korrekt den Import-Pfad angibt:
```python
@patch('claude_namer.anthropic.Anthropic')  # KORREKT
@patch('anthropic.Anthropic')               # FALSCH
```

## Zusammenfassung

✅ **23 Unit-Tests** für 3 Kern-Module
✅ **>80% Code-Coverage** Schwelle
✅ **Keine echten API-Calls** (100% Mocked)
✅ **Reproduzierbar** & **schnell** (<5s)
✅ **CI/CD ready** (GitHub Actions)

---

Für Fragen: siehe `conftest.py` für verfügbare Fixtures.
