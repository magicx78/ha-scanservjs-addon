# Paperless-AI – Fortschritt & Status

## Ziel
Automatische KI-gestützte Dokumentenklassifikation für Paperless-ngx als Home Assistant Addon,
mit Claude (Anthropic) als Klassifikations-Engine.

## Aktueller Stand (2026-03-17)

### Funktioniert ✅
- Paperless-ngx API-Anbindung (Token-Auth, CRUD)
- OCR-Text-Extraktion via Paperless API
- Claude-Klassifikation mit zwei separaten Kontexten:
  - **Tags-Kontext**: Tags, Person, Firma, Konfidenz
  - **Dateinamen-Kontext**: Datum, Kategorie, Beschreibung
- Titel-Truncation auf 128 Zeichen (Paperless API-Limit)
- Duplikat-Erkennung via MD5-Hash (SQLite)
- Home Assistant Benachrichtigungen (notify-Service)
- Polling-Script (`poll_new_docs.py`) mit Vorschau-Ausgabe
- Cron-basierter Trigger alle 5 Minuten
- Rolling-Logfile (5 MB, 3 Backups)

### Konfiguration (`config.yaml`)
| Feld | Status |
|------|--------|
| `paperless_url` | ✅ `http://ca5234a0-paperless-ngx:8000` |
| `paperless_token` | ✅ Gesetzt |
| `anthropic_api_key` | ⏳ Limit bis 01.04.2026 |
| `ha_url` | ⚠️ Noch Platzhalter |
| `ha_token` | ⚠️ Noch Platzhalter |
| `ha_notify_target` | ⚠️ Noch anpassen |

### Bekannte Einschränkungen / Offene Punkte
- Post-Consumption-Hook kann nicht direkt im HA-Addon konfiguriert werden → Cron als Workaround
- `DOCUMENT_SOURCE_PATH` nicht verfügbar im Polling-Modus → Duplikat-Check nur bei direktem Aufruf
- HA-Benachrichtigungen noch nicht getestet (Token fehlt)
- Keine Unit-Tests vorhanden
- Kein CI/CD

## Architektur

```
poll_new_docs.py (Cron, alle 5 min)
    └── auto_consume.py (pro Dokument)
            ├── duplicate_check.py   (MD5 / SQLite)
            ├── paperless_api.py     (REST API)
            ├── claude_namer.py      (2x Claude API)
            │       ├── Call 1: Tags-Kontext
            │       └── Call 2: Dateinamen-Kontext
            └── ha_notify.py         (HA REST API)
```

## Dateien
| Datei | Beschreibung |
|-------|-------------|
| `auto_consume.py` | Haupt-Orchestrierung |
| `claude_namer.py` | Claude API, 2 Prompts |
| `paperless_api.py` | Paperless REST Wrapper |
| `duplicate_check.py` | MD5-Duplikat-Erkennung |
| `ha_notify.py` | HA-Benachrichtigungen |
| `poll_new_docs.py` | Cron-Polling + Vorschau |
| `config.yaml` | Konfiguration |
| `requirements.txt` | Python-Abhängigkeiten |

## Nächste Schritte
- [ ] HA-Token und Notify-Target konfigurieren
- [ ] Unit-Tests schreiben (pytest)
- [ ] CI/CD einrichten (GitHub Actions)
- [ ] Produktionsreife-Review durchführen
