# PROGRESS.md – scanservjs-AI Addon

**Repo:** https://github.com/magicx78/ha-scanservjs-addon
**Branch:** `main`
**Aktuelle Version:** `2.4.0`
**Stand:** 2026-03-25
**Letzter Commit:** `c8730bf`

---

## Status: Produktionsreif

Addon v2.4.0 — alle 37 Unit-Tests bestehen, 58 Config-Felder vollstaendig
(options, schema, de+en translations). Keine Secrets im Repo.
HACS-kompatibel, GitHub Releases vorhanden.

Scanner: Brother MFC-L2700DW (Netzwerk), ADF Multi-Page + Flachbett mit skey-scanimage Abfrage.

---

## Was laeuft

| Komponente | Status |
|-----------|--------|
| Docker Build v2.4.0 | OK |
| scanservjs Web-UI (Port 8080) | OK |
| Brother MFC-L2700DW (`brother4:net1;dev0`) | OK |
| ADF Multi-Page Batch-Scan | OK |
| Flachbett mit skey-scanimage Abfrage | OK |
| TIFF→PDF Konvertierung (ImageMagick) | OK |
| DOC/DOCX→PDF (LibreOffice headless) | OK (neu in v2.4.0) |
| KI-Konfiguration (58 Felder) | OK |
| Paperless-AI Cron (alle 5 Min) | OK |
| Datenfresser (Folder Watcher) | OK |
| HA-Sensor-Daemon (6 Sensoren) | OK |
| Fehlerbehandlung (errors/unsupported) | OK |
| Editierbare KI-Prompts | OK |
| Scan-Rescue beim Neustart | OK (neu in v2.3.5) |
| HACS Custom Repository | OK (neu in v2.3.3) |
| Translations (de + en, 58/58) | Vollstaendig |
| Unit-Tests (37/37) | Bestanden |
| GitHub Releases | Aktuell |

---

## Versionshistorie

| Version | Was |
|---------|-----|
| 2.4.0 | DOC/DOCX-Support: LibreOffice headless konvertiert Word-Dokumente nach PDF |
| 2.3.5 | Scan-Rescue: verwaiste Scans beim Neustart in Datenfresser-Inbox retten |
| 2.3.4 | ImageMagick fehlte im Docker-Image, PDF-Policy entsperrt |
| 2.3.3 | HACS-Kompatibilitaet, Badges, GitHub Issues, Bugfixes, Release-Workflow |
| 2.3.2 | Flachbett Multi-Page entfernt (Scanner blockiert Tasten), skey-scanimage Fallback |
| 2.3.1 | ADF-Autodiscovery: detect_adf_source() erkennt korrekten Source-Namen |
| 2.3.0 | Multi-Page ADF-Scan: Brother-Buttons scannen alle Seiten vom ADF, merge zu PDF |
| 2.2.1 | HA-Sensoren Bugfix: falscher config.yaml Pfad, SUPERVISOR_TOKEN |
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
       |-- ADF: scanimage --batch -> Multi-Page PDF
       |-- FB:  skey-scanimage (mit "Weitere Seite?"-Abfrage)
       +-- -> TIFF->PDF (ImageMagick) -> /share/paperless/consume/
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
  |-- Formate: PDF, JPG, PNG, TIFF, DOC, DOCX
  |-- DOC/DOCX -> LibreOffice headless -> PDF
  |-- OCR (ocrmypdf/tesseract)
  |-- -> consume (OK) | errors (3x) | unsupported | duplicates

[ha_sensors.py Daemon (60s)]
  +-- 6 Sensoren an HA REST API

[Scan-Rescue beim Start]
  +-- button_*.{tif,jpg,pdf,...} aus /data/output -> datenfresser/inbox
```

---

## Quality Gate v2.4.0

| Pruefung | Ergebnis |
|----------|----------|
| Shell Syntax (7 Scripts) | OK |
| Python Syntax (10 Scripts) | OK |
| YAML Syntax (3 Dateien) | OK |
| Config Vollstaendigkeit (58/58) | OK |
| Unit-Tests (37/37) | Bestanden |
| Secrets-Check | Sauber |
| Brother-skey Sync (AI/non-AI) | OK |
| GitHub Release v2.4.0 | Ausstehend |

---

## Offene Punkte

| # | Was | Prioritaet |
|---|-----|-----------|
| 1 | End-to-End: Web-UI Scan -> KI -> Panels | MITTEL |
| 2 | KI-Prompts anpassen und Ergebnis pruefen | NIEDRIG |
| 3 | aarch64 Support evaluieren | NIEDRIG |

---

## Zukunft (zurueckgestellt)

- **Drucken:** PDF in Print-Ordner -> Brother druckt (CUPS-Integration)
- **Office-Dokumente schreiben:** LibreOffice Online als separates Addon

---

## Bekannte Eigenheiten

- `scanimage -L fehlgeschlagen` beim Start -> Normal (brsaneconfig4 registriert)
- brscan-skey Prozess-Check uneindeutig -> Normal
- brscan4 bei jedem Start frisch installiert (~10 Sek)
- KI-Panels nur auf Screens >= 1264px
- ADF Exit-Code 7 ("no more pages") ist kein Fehler
- LibreOffice erster Start braucht ~5 Sek (Profil-Initialisierung)
