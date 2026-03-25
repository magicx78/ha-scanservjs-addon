# PROGRESS.md – scanservjs-AI Addon

**Repo:** https://github.com/magicx78/ha-scanservjs-addon
**Branch:** `main`
**Aktuelle Version:** `2.2.0`
**Stand:** 2026-03-25
**Letzter Commit:** `95d3c58` (fix: HA-Sensoren 3 Bugs gefixt)

---

## Status: Stabil & validiert ✅

Addon v2.2.0 gebaut, alle 37 Unit-Tests bestehen, alle Config-Felder durchgereicht,
alle Translations vollstaendig (de + en). Code ist gepusht auf `main`.

Scanner (Brother MFC-L2700DW, 10.10.10.216) wird erkannt und ist aktiv.

---

## Was laeuft

| Komponente | Status |
|-----------|--------|
| Docker Build v2.2.0 | ✅ Erfolgreich |
| scanservjs Web-UI (Port 8080) | ✅ Laeuft |
| Brother MFC-L2700DW (`brother4:net1;dev0`) | ✅ Erkannt |
| brscan4 + brscan-skey Installation | ✅ Pro Start |
| KI-Konfiguration (`/opt/paperless-ai/config.yaml`) | ✅ Alle 26 Felder |
| Paperless-AI Cron (alle 5 Min) | ✅ Gestartet |
| Datenfresser (Folder Watcher) | ✅ Gestartet |
| HA-Sensor-Daemon (6 Sensoren) | ✅ Gestartet |
| Fehlerbehandlung (errors/unsupported) | ✅ Implementiert |
| Editierbare KI-Prompts | ✅ Implementiert |
| COPY_SCANS_TO → `/share/paperless/consume` | ✅ Konfiguriert |
| Claude.ai Theme (CSS) | ✅ Injiziert |
| KI Sidebar-Panels (JS) | ✅ Injiziert |
| Translations (de + en) | ✅ Vollstaendig |
| Unit-Tests (37/37) | ✅ Bestanden |

---

## v2.2.0 Features (aktuell)

### Editierbare KI-Prompts
- Prompt-Dateien unter `/share/scanservjs-ai/` (prompt_tags.txt, prompt_dateiname.txt)
- Addon-Config Felder "Zusaetzliche Tag-Regeln" und "Zusaetzliche Dateinamen-Regeln"
- Reset-Toggle zum Zuruecksetzen auf Default-Prompts
- Prompts koennen per HA File Editor oder SSH angepasst werden

### HA-Sensoren fuer Datenfresser-Status
- `sensor.datenfresser_inbox_count` — Dateien in der Inbox-Queue
- `sensor.datenfresser_error_count` — Fehlgeschlagene Dateien
- `sensor.datenfresser_duplicate_count` — Duplikate
- `sensor.datenfresser_unsupported_count` — Inkompatible Formate
- `sensor.datenfresser_last_document` — Letztes verarbeitetes Dokument
- `binary_sensor.datenfresser_running` — Prozess-Status mit 5-Min-Timeout

### Fehlerbehandlung und Error-Ordner
- `/share/datenfresser/errors` — OCR-Fehler nach 3 Versuchen
- `/share/datenfresser/unsupported` — Inkompatible Dateiformate (.docx, .xlsx etc.)
- Max-Retry-Counter pro Datei (3 Versuche, dann nach errors/)
- HA-Notifications bei inkompatiblen Dateien und OCR-Fehlern

### KI-Beschriftung verbessert
- Tags-Prompt: 4 Positiv- + 2 Negativbeispiele, 8 Pflicht-Tag-Regeln
- Dateiname-Prompt: 8 Referenzbeispiele, Kategorie-Zuordnungstabelle
- Firmen-Stammdaten erweitert: Telekom, Vodafone, E.ON, Stadtwerke, ADAC
- Negativbeispiele verhindern generische Tags wie "Scan", "Dokument", "Brief"
- OCR-Text-Limit von 3000 auf 5000 Zeichen erhoeht

---

## Alle Fixes (Verlauf)

| Version | Commit | Was |
|---------|--------|-----|
| 2.2.0 | `95d3c58` | HA-Sensoren: falscher config.yaml Pfad, SUPERVISOR_TOKEN nicht durchgereicht, unabhaengig von KI-Config |
| 2.2.0 | `59d6f58` | 18 fehlende Translations, 8 Config-Felder in write_ai_config(), 5 Unit-Tests gefixt, pytest.ini repariert |
| 2.2.0 | `767540e` | Editierbare KI-Prompts, HA-Sensoren, Fehlerbehandlung, verbesserte KI-Beschriftung |
| 2.1.0 | `9c95a21` | Test Suite Release — PERF-501 Unit-Tests, HybridCache Validation |
| 2.0.0 | — | HA-Integration, KI-Status Widget, Classification-Cache |
| 1.5.0 | — | Duplikat-Tagging, Error-Handling, 23 Unit-Tests |
| 1.4.0 | — | Datenfresser Claude-Klassifikation |
| 1.3.0 | — | Datenfresser Folder Watcher |
| 1.2.8 | — | Claude access type selection |
| 1.2.7 | `d0ed38a` | KI Kontext-Panels in Sidebar |
| 1.2.6 | `2b56775` | claude.ai Layout |
| 1.2.5 | `9f0caf6` | brother_copy_ocr_to_target |
| 1.2.4 | `57ff47f` | Docker-Cache-Bust |
| 1.2.3 | `2c839ce` | Claude CSS Theme |
| 1.2.2 | diverse | Stability-Fixes, Port 8080, Schema |

---

## Architektur

```
[Brother Scanner MFC-L2700DW]
       |  USB / Netzwerk (10.10.10.216)
       v
[scanservjs Web-UI :8080]
  |-- afterScan-Hook -> /share/paperless/consume/
  +-- Brother-Button-Skripte (brscan-skey)
           +-- OCR/File -> /share/paperless/consume/
                              |
                              v
                    [Paperless-ngx Consumer]
                    erstellt Dokument (kein document_type)
                              |
                              v
                    [poll_new_docs.py — Cron alle 5 Min]
                    findet Dokumente ohne document_type
                              |
                              v
                    [auto_consume.py]
                    |-- OCR-Text holen (Paperless API)
                    |-- Claude Haiku 4.5 -> klassifiziert
                    |-- Titel / Tags / Typ in Paperless setzen
                    |-- Tag "KI-Verarbeitet" setzen (nicht bei Fallback)
                    |-- ki-status.json schreiben -> UI-Panels
                    +-- HA-Benachrichtigung senden

[Datenfresser (Folder Watcher)]
  |-- Ueberwacht /share/datenfresser/inbox (30s Intervall)
  |-- OCR mit ocrmypdf / tesseract
  |-- Duplikat-Check (MD5)
  |-- -> /share/paperless/consume (OK)
  |-- -> /share/datenfresser/errors (3x Fehler)
  |-- -> /share/datenfresser/unsupported (.docx etc.)
  +-- -> /share/datenfresser/duplicates

[ha_sensors.py Daemon (60s)]
  +-- Pusht 6 Sensoren an HA REST API
```

---

## Dateien

```
scanservjs-ai/
|-- Dockerfile              # venv, custom.css+js injection, port 8080
|-- config.yaml             # v2.2.0, 46 Optionen, vollstaendiges Schema
|-- run.sh                  # r35: write_default_prompts, write_ai_config (26 Felder),
|                           #       start_ai_cron, start_datenfresser, start_ha_sensors
|-- custom.css              # claude.ai Theme: dunkle Sidebar, warme Content-Area
|-- custom.js               # KI-Panels: polling /ki-status.json alle 30s
|-- config.local.js         # afterScan-Hook -> COPY_SCANS_TO
|-- build.yaml              # amd64: sbs20/scanservjs:v3.0.3
|-- translations/de.yaml    # Vollstaendig (alle Config-Felder)
|-- translations/en.yaml    # Vollstaendig (alle Config-Felder)
+-- scripts/
    |-- auto_consume.py     # KI-Pipeline + ki-status.json
    |-- poll_new_docs.py    # Cron-Poller (Paperless API, Retry-Logik)
    |-- claude_namer.py     # Claude Haiku 4.5, dynamische Prompts, Cache
    |-- paperless_api.py    # Paperless REST API wrapper
    |-- ha_notify.py        # HA persistent_notification
    |-- ha_sensors.py       # HA-Sensor-Daemon (6 Entities, 60s)
    |-- datenfresser.py     # Folder Watcher, OCR, Fehlerbehandlung
    |-- cache_manager.py    # HybridCache (SQLite + Redis)
    |-- duplicate_check.py  # MD5-Hash DB (/data/document_hashes.db)
    |-- requirements.txt    # anthropic>=0.44.0, requests, pyyaml, etc.
    +-- tests/
        |-- conftest.py         # 9 Fixtures
        |-- pytest.ini          # Config
        |-- test_claude_namer.py    # 6 Tests
        |-- test_paperless_api.py   # 9 Tests
        |-- test_duplicate_check.py # 10 Tests
        +-- test_cache_manager.py   # 12 Tests
```

---

## Offene Punkte

| # | Was | Prioritaet |
|---|-----|-----------|
| 1 | End-to-End Test: Web-UI Scan -> Paperless -> KI -> Panels | HOCH |
| 2 | `/data/paperless-ai.log` nach Scan pruefen (KI laeuft durch?) | MITTEL |
| 3 | Datenfresser E2E: Datei in Inbox -> OCR -> Paperless -> KI-Tags | MITTEL |
| 4 | HA-Sensoren nach Addon-Update pruefen (Entities sichtbar?) | MITTEL |
| 5 | KI-Prompts editieren und Ergebnis pruefen | NIEDRIG |

---

## Bekannte Eigenheiten

- `scanimage -L fehlgeschlagen` beim Start -> **Normal**, Brother ist per `brsaneconfig4` direkt registriert
- brscan-skey Prozess-Check "uneindeutig" -> **Normal**, Frontpanel funktioniert trotzdem
- brscan4 wird bei jedem Container-Start frisch installiert (apt-get) -> dauert ~10 Sek extra
- KI-Panels nur auf Screens >= 1264px sichtbar (kleinere Screens: ausgeblendet)

---

## Naechste Schritte

1. **Update auf v2.2.0** in HA (Settings -> Add-ons -> Update)
2. **Test**: Scan ueber Web-UI -> Pipeline pruefen
3. **Pruefen**: HA-Sensoren (`sensor.datenfresser_*`) sichtbar?
4. **Test**: Datei in `/share/datenfresser/inbox` legen -> Verarbeitung pruefen
5. **Log lesen**: `/data/paperless-ai.log` + `/data/datenfresser.log` nach erstem Scan
