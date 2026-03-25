# Changelog

## [2.3.3] - 2026-03-25

### Fixed
- **Scan-Button tat nichts:** ADF-Fallback auf Single-Page setzte `--source ADF` statt `--source FB` — skey-scanimage versuchte vom nicht-vorhandenen ADF zu scannen und scheiterte still. Jetzt wird `BROTHER_SCAN_SOURCE=FB` erzwungen bevor der Flachbett-Pfad ausgefuehrt wird.

## [2.3.2] - 2026-03-25

### Fixed
- **Flachbett Multi-Page entfernt:** Brother-Scanner blockiert Tasten waehrend brscan-skey laeuft — Multi-Page per Button-Druck nicht moeglich. Flachbett scannt jetzt zuverlaessig eine Einzelseite.
- **Signal-Datei-Logik entfernt:** `/tmp/brother_scan_waiting` und `/tmp/brother_scan_continue` Mechanismus aus allen 4 Button-Scripts entfernt (funktionierte nicht, da Scanner-Display "Scannen" zeigt und Tasten sperrt)
- **ADF Fallback verbessert:** Bei ADF-Fehler oder fehlendem ADF wird jetzt sauber auf eine Einzelseite Flachbett zurueckgefallen

## [2.3.1] - 2026-03-25

### Fixed
- **ADF-Scan Exit-Code 1 behoben:** `detect_adf_source()` erkennt jetzt den korrekten ADF-Source-Namen automatisch (z.B. "Automatic Document Feeder(left aligned)" statt nur "ADF")
- **Flachbett Multi-Page wiederhergestellt:** Wenn kein ADF erkannt wird oder ADF fehlschlaegt, scannt vom Flachbett mit Wartezeit (30s Standard). Naechsten Button druecken = naechste Seite scannen. Kein Button = fertig, alle Seiten zu PDF mergen.
- **Alle 4 Button-Scripts** (OCR/File/Email/Image) erkennen laufenden Multi-Page-Scan und senden "weiter"-Signal statt neuen Scan zu starten

### Added
- Neue Config-Option `brother_multipage_wait` (Sekunden, Standard: 30) fuer Flachbett-Wartezeit

## [2.3.0] - 2026-03-25

### Added
- **Multi-Page ADF-Scan:** Brother OCR/File/Email-Button scannt jetzt alle Seiten vom ADF und fasst sie automatisch zu einem PDF zusammen
  - Neue Config-Option `brother_scan_source: "ADF"` (Standard) vs. `"FB"` (Flachbett)
  - `scanimage --batch` mit automatischer Exit-Code-7-Erkennung ("ADF leer")
  - ImageMagick-Merge: Einzelseiten-TIFFs → ein Multi-Page-PDF
  - Fallback bei 1 Seite: normales Single-Page-Verhalten
  - MFC-L2700DW ADF fasst bis zu 35 Seiten

## [2.2.1] - 2026-03-25

### Fixed
- **HA-Sensoren erschienen nicht:** `ha_sensors.py` las config.yaml aus falschem Pfad (`/opt/` statt `/opt/paperless-ai/`)
- **SUPERVISOR_TOKEN** wurde nicht an den Sensor-Daemon durchgereicht — jetzt wird es direkt als Env-Var gelesen
- **Sensor-Daemon startete nicht** wenn Claude-API-Key fehlte — Sensoren laufen jetzt unabhaengig von der KI-Konfiguration

## [2.2.0] - 2026-03-25

### Added
- **Editierbare KI-Prompts:**
  - Prompt-Dateien unter `/share/scanservjs-ai/` (prompt_tags.txt, prompt_dateiname.txt)
  - Addon-Config Felder "Zusaetzliche Tag-Regeln" und "Zusaetzliche Dateinamen-Regeln"
  - Reset-Toggle zum Zuruecksetzen auf Default-Prompts
  - Prompts koennen per HA File Editor oder SSH angepasst werden

- **HA-Sensoren fuer Datenfresser-Status (NEU):**
  - `sensor.datenfresser_inbox_count` — Dateien in der Inbox-Queue
  - `sensor.datenfresser_error_count` — Fehlgeschlagene Dateien
  - `sensor.datenfresser_duplicate_count` — Duplikate
  - `sensor.datenfresser_unsupported_count` — Inkompatible Formate
  - `sensor.datenfresser_last_document` — Letztes verarbeitetes Dokument
  - `binary_sensor.datenfresser_running` — Prozess-Status mit 5-Min-Timeout
  - Neues Script `ha_sensors.py` als Hintergrund-Daemon (60s Intervall)

- **Fehlerbehandlung und Error-Ordner (NEU):**
  - `/share/datenfresser/errors` — OCR-Fehler nach 3 Versuchen
  - `/share/datenfresser/unsupported` — Inkompatible Dateiformate (.docx, .xlsx etc.)
  - Max-Retry-Counter pro Datei (3 Versuche, dann nach errors/)
  - HA-Notifications bei inkompatiblen Dateien und OCR-Fehlern
  - Status-Datei `/data/datenfresser-status.json` fuer HA-Sensoren

### Improved
- **KI-Beschriftung deutlich verbessert:**
  - Tags-Prompt: 4 Positiv- + 2 Negativbeispiele, 8 Pflicht-Tag-Regeln (vorher 4)
  - Dateiname-Prompt: 8 Referenzbeispiele (vorher 2), Kategorie-Zuordnungstabelle
  - Firmen-Stammdaten erweitert: Telekom, Vodafone, E.ON, Stadtwerke, ADAC
  - Beschreibung muss jetzt Absender/Firma und Dokumenttyp enthalten
  - Negativbeispiele verhindern generische Tags wie "Scan", "Dokument", "Brief"
  - OCR-Text-Limit von 3000 auf 5000 Zeichen erhoeht

### Fixed
- YAML-Injection in `write_ai_config()` durch `yaml_escape()` Funktion behoben
- Versteckte Dateien (`.scan_temp.pdf`) werden jetzt immer ignoriert (Check vor Extension-Pruefung)
- KI-Fallback-Dokumente bekommen nicht mehr faelschlicherweise `[KI-Verarbeitet]` Tag
- Doppelte MD5-Berechnung in `classify()` entfernt
- `retry_counts` Memory-Leak bei langem Betrieb behoben (Cleanup bei >1000 Eintraegen)
- Fallback-Tag von `[Pruefen]` auf `[KI-Fehler]` geaendert (klar unterscheidbar)

## [2.1.0] - 2026-03-22

### Testing
- **Unit-Tests für HybridCache (PERF-501 Validation):**
  - 12 Unit-Tests für SQLite-Cache + Redis-Mock
  - 8 SQLite-Tests: init, get/set, TTL-Expiry, cleanup, invalidate
  - 4 Redis-Tests: HIT, Fallback, Error-Handling, no-Redis-mode
  - @pytest.mark.unit, @pytest.mark.slow, @pytest.mark.mock Markers
  - Alle kritischen Branches abgedeckt für >80% Coverage-Target

- **conftest.py Erweiterung:**
  - Neue Fixture `mock_redis_client` für Cache-Tests
  - Wiederverwendet: `mock_logger`, `temp_db_path`

### Changed
- Version: 2.0.0 → 2.1.0 (Test-Suite hinzugefügt)

## [2.0.0] - 2026-03-22

### Added
- **HA-Integration (HA-501):**
  - Native Home Assistant Notifications für KI-Klassifikationen
  - Automation-Trigger bei neuen Dokumenten (`ha_automation_entity_id`)
  - Konfigurierbare Benachrichtigungs-Targets (notify.* Services)
  - Graceful Error-Handling (Benachrichtigungen blockieren nicht den Hauptfluss)

- **KI-Status Real-time Widget (UI-501):**
  - Live-Dashboard für letzte klassifizierte Dokumente
  - Echtzeit-Anzeige: Titel, Tags, Kategorie, Konfidenz (%)
  - `/ki-status.json` API-Endpoint (statisch von datenfresser.py geschrieben)
  - custom.js erweitert mit neuer Kategorie/Konfidenz-Panel
  - 30s Polling-Interval (konfigurierbar)

- **Performance: Classification-Cache (PERF-501):**
  - Hybrid-Cache für Claude-Klassifikationen (SQLite + optional Redis)
  - Basis: SQLite mit WAL, Indexes für schnelle Lookups
  - Optional: Redis als L1-Cache für verteilte Systeme
  - TTL-Management (24h Standard, konfigurierbar)
  - MD5-basierte Input-Hashing (für Duplikat-Erkennung auf Klassifikationsebene)
  - Cache-Cleanup-Utility für abgelaufene Einträge

### Improved
- **datenfresser.py:**
  - HANotifier Integration für HA-Benachrichtigungen
  - `write_ki_status()` für Echtzeit-UI-Updates
  - Bessere Fehlerbehandlung bei Cache-Operationen

- **claude_namer.py:**
  - HybridCache vor/nach API-Calls
  - Graceful Fallback bei fehlender Redis
  - Reduzierte API-Calls durch intelligentes Caching

- **config.yaml:**
  - 12 neue Optionen (HA + Cache)
  - `cache_enabled` (deaktivierbar für minimale Footprint)
  - `redis_url` optional (nur für Enterprise-Setups)

### Changed
- Version: 1.5.0 → 2.0.0

## [1.5.0] - 2026-03-22

### Added
- **Datenfresser Duplikat-Tagging (DF-501):**
  - Duplikate werden nun auch zu consume/ verarbeitet (nicht nur zu duplicates/)
  - JSON-Marker mit `is_duplicate: true` + Original-Referenz
  - auto_consume.py erkennt Duplikate und setzt nur [Duplikat]-Tag
  - Duplikate jetzt in Paperless trackbar und taggbar

### Improved
- **poll_new_docs.py Error-Handling (PW-501):**
  - Intelligente Retry-Logik mit exponential backoff (15s → 30s → 60s → 120s max)
  - Spezifisches Exception-Handling für verschiedene Fehlertypen:
    - Timeout: Retry mit Backoff
    - Connection Error: Retry mit Backoff
    - Auth Error (401/403): Kein Retry (permanent)
    - Server Error (5xx): Retry mit Backoff
  - Konfigurierbare Max-Retries + Request-Timeout
  - Strukturiertes Logging für HA-Integration
  - Graceful Degradation bei permanenten Fehlern

### Testing
- **Unit-Tests Setup (TEST-501):**
  - 23 Unit-Tests für 3 Kern-Module (claude_namer, paperless_api, duplicate_check)
  - >80% Code-Coverage Ziel
  - 100% Mocked (keine echten API-Calls)
  - pytest + Coverage-Konfiguration
  - Makefile für Test-Kommandos
  - CI/CD Ready (GitHub Actions prepared)

### Changed
- poll_new_docs.py: Strukturiertes Logging statt print()
- Tests sind produktionsreif für Docker-Integration

## [1.4.0] - 2026-03-22

### Added
- **Datenfresser Claude-Klassifikation** — Erweiterte Dokumentenverarbeitung mit KI-gestütztem Tagging:
  - Automatische OCR-Text-Klassifikation via Claude API (optional)
  - Kategorie-, Tag-, Person-, Firma-Extraktion
  - Vorberechnete Classifications werden in Cache-Verzeichnis gespeichert
  - auto_consume.py nutzt Datenfresser-Classifications wenn verfügbar (fallback zu Live-Claude)
  - Konfidenz-Tracking für manuelle Validierung (Prüfen-Tag bei niedriger Konfidenz)

### Improved
- **Klassifikations-Workflow optimiert:**
  - Duplicate-Check zuerst (spart OCR für Duplikate)
  - Paperless-Kontext vor OCR abrufbar (vorbereitet für zukünftige Erweiterungen)
  - Intelligentes Fallback: Datenfresser-Cache vor Live-Claude API
  - Strukturierte JSON-Metadata in `/share/datenfresser/cache/` für inter-process Kommunikation

### Changed
- Datenfresser jetzt mit optionaler Claude-Klassifikation (deaktivierbar via `claude_access_type: none`)
- auto_consume.py: Erweiterte Logik zum Laden und Anwenden von Datenfresser-Classifications

## [1.3.0] - 2026-03-22

### Added
- **Datenfresser** — Folder watcher for automatic document processing:
  - Monitors inbox folder for new documents (PDF, JPG, PNG, TIFF)
  - MD5-based duplicate detection (reuses existing hash database)
  - Automatic OCR with ocrmypdf (PDFs) and tesseract (images)
  - German+English language support (configurable)
  - Automatic file organization: non-duplicates → consume folder
- Configurable poll interval (default: 30s)
- Configurable inbox/duplicates paths

### Improved
- **Stability & Error Handling:**
  - Exclusive lock file prevents parallel instances
  - Retry logic for OCR operations (2 retries with backoff)
  - Improved timeout handling (180s for large PDFs)
  - Memory leak prevention: seen-set auto-cleanup
  - Exception handling with error counter (auto-recovery)
  - Graceful degradation on failures
  - Comprehensive logging and error reporting
  - Keyboard interrupt handling
- Docker dependencies: added tesseract-ocr, ocrmypdf, poppler-utils

## [1.2.8] - 2026-03-21

### Added
- Claude access type selection in config: `api_key`, `subscription`, or `none`
- UX improvement for users with different Claude subscription types
- Config option `claude_access_type` to differentiate API usage patterns

### Changed
- VERSION file now synced with addon version (1.2.8)
- AI config generation now respects `claude_access_type` setting

### Fixed
- When `claude_access_type` is set to `none`, KI-Klassifikation is gracefully disabled

## [1.0.13] - 2026-03-16

### Fixed
- Startup now pre-creates `/var/lib/snmp/cert_indexes` before `scanimage -L`, reducing the one-time warning:
  - `scanimage -L fehlgeschlagen: Created directory: /var/lib/snmp/cert_indexes`

### Changed
- Runtime revision bumped to `2026-03-16-r29`.

## [1.0.12] - 2026-03-16

### Added
- Generic scanner fallback option `generic_scanner_ip` for non-Brother network MFPs.
- Extended documentation for HP/Epson/Canon/Xerox-style generic SANE/AirScan setups.

### Changed
- Runtime revision bumped to `2026-03-16-r28`.
- Startup fallback now prefers `generic_scanner_ip` and still falls back to `brother_scanner_ip` for compatibility.

### Validation
- HAOS validation passed for `v1.0.12` / `Runtime-Revision: 2026-03-16-r28`.
- Add-on starts without restart loop and reaches `Starte scanservjs`.
- `/api/v1/context` resolves Brother device `brother4:net1;dev0`.
- Brother frontpanel `File/Email/Image/OCR` runs end-to-end.
- Generic SANE path remains unchanged; only fallback selection was extended (`generic_scanner_ip` first, then legacy Brother IP fallback).

## [1.0.11] - 2026-03-16

### Added
- Brother frontpanel runtime options in add-on config:
  - per-button copy routing (`brother_copy_*_to_target`)
  - output format controls for image/ocr (`brother_image_output_format`, `brother_ocr_output_format`)
  - default Brother button DPI fallback (`brother_button_default_resolution`)
  - optional Brother button output directory (`brother_button_output_dir`)
- `copy_scans_to_mode` (`auto|paperless|custom`) for clearer scan target selection.
- Preset documentation for common HA/Paperless workflows.

### Changed
- Brother button scans now default to scanservjs `data/output`, making them visible in the scanservjs `Files` tab.
- Brother `brscan-skey` package download now tries the current URL first and only falls back to legacy URL if needed.
- Add-on app/store icon updated.

### Fixed
- Resolved restart loop caused by non-fatal `brscan-skey` process check under `set -e`.
- `Scan to Image` and `Scan to OCR` now run a real scan before webhook trigger.
- Paperless ingest compatibility improved by auto-converting Brother TIFF copies to JPG when target is `/share/paperless...`.

### Validation
- HAOS smoke validation passed for `v1.0.11` / `Runtime-Revision: 2026-03-16-r27`:
  - add-on starts without restart loop
  - `Starte scanservjs` reached
  - `/api/v1/context` returns Brother device (`brother4:net1;dev0`)
  - generic Web/API scanning works
  - Brother frontpanel `File/Email/Image/OCR` verified end-to-end

## [1.0.0] - 2026-03-16

### Added
- Optional Brother `brscan4` installation with explicit EULA gating.
- Optional Brother network scanner registration for devices such as the MFC-L2700DW.
- Fallback feature flag `ENABLE_BROTHER_SUPPORT=false` for generic SANE-only startup.
- GitHub Actions CI for YAML linting, shell validation, Node syntax checks, Docker build, and Trivy scanning.
- Repository maintenance files: issue templates, pull request template, security policy, and Dependabot.

### Changed
- Migrated Home Assistant addon metadata to `config.yaml` and `build.yaml`.
- Limited the supported architecture to `amd64` for a predictable release target.
- Fixed copy destination handling so `copy_scans_to` is honored.
- Improved startup idempotency for `saned_net_hosts`, `airscan_devices`, and Brother registration.
- Added LF enforcement through `.gitattributes`.

### Fixed
- Removed deprecated Debian Stretch based addon build metadata.
- Cleaned package management steps in the Docker image and at Brother driver install time.
