# PROGRESS.md – scanservjs-AI Addon

**Repo:** https://github.com/magicx78/ha-scanservjs-addon
**Branch:** `main`
**Aktuelle Version:** `2.3.3`
**Stand:** 2026-03-25
**Letzter Commit:** `762919c`

---

## Status: Stabil & validiert

Addon v2.3.3 gebaut, alle 37 Unit-Tests bestehen, alle Config-Felder durchgereicht,
alle Translations vollstaendig (de + en). Keine Secrets im Repo.
HACS-kompatibel, GitHub Release vorhanden.

Scanner: Brother MFC-L2700DW (Netzwerk), ADF Multi-Page aktiv.

---

## Was laeuft

| Komponente | Status |
|-----------|--------|
| Docker Build v2.3.3 | OK |
| scanservjs Web-UI (Port 8080) | OK |
| Brother MFC-L2700DW (`brother4:net1;dev0`) | OK |
| ADF Multi-Page Batch-Scan | OK (neu in v2.3.0) |
| KI-Konfiguration (26+ Felder) | OK |
| Paperless-AI Cron (alle 5 Min) | OK |
| Datenfresser (Folder Watcher) | OK |
| HA-Sensor-Daemon (6 Sensoren) | OK |
| Fehlerbehandlung (errors/unsupported) | OK |
| Editierbare KI-Prompts | OK |
| Translations (de + en) | Vollstaendig |
| Unit-Tests (37/37) | Bestanden |

---

## Versionshistorie

| Version | Was |
|---------|-----|
| 2.3.3 | ADF-Fallback fix: source=FB erzwingen, HACS-Release, Badges, Bugfixes |
| 2.3.2 | Flachbett Multi-Page entfernt (Scanner blockiert Tasten), Signal-Dateien entfernt |
| 2.3.1 | ADF-Autodiscovery: detect_adf_source() erkennt korrekten Source-Namen automatisch |
| 2.3.0 | Multi-Page ADF-Scan: Brother-Buttons scannen alle Seiten vom ADF, merge zu PDF |
| 2.2.1 | HA-Sensoren Bugfix: falscher config.yaml Pfad, SUPERVISOR_TOKEN, unabhaengig von KI-Config |
| 2.2.0 | Editierbare KI-Prompts, HA-Sensoren, Fehlerbehandlung, verbesserte KI-Beschriftung |
| 2.1.0 | Test Suite: 12 HybridCache Unit-Tests |
| 2.0.0 | HA-Integration, KI-Status Widget, Classification-Cache |
| 1.5.0 | Duplikat-Tagging, Error-Handling, 23 Unit-Tests |
| 1.4.0 | Datenfresser Claude-Klassifikation |
| 1.3.0 | Datenfresser Folder Watcher |
| 1.2.x | Brother-Support, CSS Theme, KI-Panels, Stability-Fixes |

---

## Architektur

```
[Brother MFC-L2700DW]
       |  Netzwerk
       v
[scanservjs Web-UI :8080]
  |-- afterScan-Hook -> /share/paperless/consume/
  +-- Brother-Button-Skripte (brscan-skey)
       |-- ADF: scanimage --batch -> Multi-Page PDF (v2.3.0)
       |-- FB:  Single-Page Scan (Flachbett)
       +-- -> /share/paperless/consume/
                          |
                          v
                [Paperless-ngx Consumer]
                          |
                          v
                [poll_new_docs.py — Cron alle 5 Min]
                          |
                          v
                [auto_consume.py]
                |-- Claude Haiku 4.5 -> Tags, Kategorie, Dateiname
                |-- Paperless Metadaten setzen
                |-- ki-status.json -> UI-Panels
                +-- HA-Benachrichtigung

[Datenfresser (Folder Watcher)]
  |-- /share/datenfresser/inbox (30s)
  |-- OCR (ocrmypdf/tesseract)
  |-- -> consume (OK) | errors (3x) | unsupported | duplicates

[ha_sensors.py Daemon (60s)]
  +-- 6 Sensoren an HA REST API
```

---

## Dateien

```
scanservjs-ai/
|-- Dockerfile
|-- config.yaml             # v2.3.3, ~50 Optionen
|-- run.sh
|-- brother-skey/
|   |-- common.sh           # scan_batch_from_adf() + scan_via_profile()
|   |-- scantoocr.sh
|   |-- scantofile.sh
|   |-- scantoemail.sh
|   +-- scantoimage.sh
|-- custom.css / custom.js
|-- config.local.js
|-- build.yaml
|-- translations/de.yaml
|-- translations/en.yaml
+-- scripts/
    |-- auto_consume.py
    |-- poll_new_docs.py
    |-- claude_namer.py
    |-- paperless_api.py
    |-- ha_notify.py
    |-- ha_sensors.py
    |-- datenfresser.py
    |-- cache_manager.py
    |-- duplicate_check.py
    |-- requirements.txt
    +-- tests/ (37 Tests)
```

---

## Offene Punkte

| # | Was | Prioritaet |
|---|-----|-----------|
| 1 | End-to-End: Web-UI Scan -> KI -> Panels | MITTEL |
| 2 | KI-Prompts anpassen und Ergebnis pruefen | NIEDRIG |
| 3 | aarch64 Support evaluieren | NIEDRIG |

---

## Bekannte Eigenheiten

- `scanimage -L fehlgeschlagen` beim Start -> Normal (brsaneconfig4 registriert)
- brscan-skey Prozess-Check uneindeutig -> Normal
- brscan4 bei jedem Start frisch installiert (~10 Sek)
- KI-Panels nur auf Screens >= 1264px
- ADF Exit-Code 7 ("no more pages") ist kein Fehler

---

## Naechste Schritte

1. HACS: Repo-URL in HACS als Custom Repository hinzufuegen und testen
2. End-to-End Scan-Workflow validieren (Web-UI -> KI -> Paperless)
3. KI-Prompts optimieren und Ergebnis pruefen
