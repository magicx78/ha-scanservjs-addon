# Paperless-AI – Fortschritt & Status

_Zuletzt aktualisiert: 2026-03-17_

## Ziel
Automatische KI-gestützte Dokumentenklassifikation für Paperless-ngx als Home Assistant Addon,
mit Claude (Anthropic) als Klassifikations-Engine.

---

## Aktueller Stand ✅ ERLEDIGT

### Produktionsreife-Fixes (alle committed & gepusht auf `claude/integrate-paperless-ai-gxaos`)

| Fix | Datei | Status |
|-----|-------|--------|
| Env-Var-Overrides für Secrets | `auto_consume.py`, `poll_new_docs.py` | ✅ |
| Startup-Validierung Pflichtfelder | `auto_consume.py` | ✅ |
| `.env.example` Template | `scripts/.env.example` | ✅ |
| `.gitignore` (secrets, logs, db) | `.gitignore` | ✅ |
| `fcntl.flock` Process-Lock | `poll_new_docs.py` | ✅ |
| Tag `"KI-Verarbeitet"` nach Klassifikation | `auto_consume.py` | ✅ |
| `JSONDecodeError`-Schutz alle API-Calls | `paperless_api.py` | ✅ |
| SQLite WAL-Mode | `duplicate_check.py` | ✅ |
| Titel-Truncation 128 Zeichen | `auto_consume.py` | ✅ |
| Zwei separate Claude-Kontexte | `claude_namer.py` | ✅ |
| Vorschau-Liste (vor/nach Klassifikation) | `poll_new_docs.py` | ✅ |

### Kernfunktionen
- ✅ Paperless-ngx API-Anbindung (Token-Auth, GET/PATCH/POST)
- ✅ OCR-Text-Extraktion via Paperless API + PDF-Fallback (pdfminer)
- ✅ Claude-Klassifikation: **Tags-Kontext** + **Dateinamen-Kontext** (2 separate Calls)
- ✅ Duplikat-Erkennung via MD5-Hash (SQLite WAL)
- ✅ HA-Benachrichtigungen (graceful disabled wenn Token fehlt)
- ✅ Cron-Polling alle 5 Minuten mit Dokumenten-Vorschau
- ✅ Rolling-Logfile (5 MB, 3 Backups)
- ✅ Konfidenz-Check: Tag `[Pruefen]` bei < 0.7

---

## Sprint 2 ✅ Abgeschlossen (2026-03-17)

| ID | Task | Status |
|----|------|--------|
| TEST-01..05 | 32 pytest-Tests (API, OCR, Claude, Duplikat, Titel) | ✅ alle grün |
| CI-01 | GitHub Actions ci.yml (ruff + pytest) | ✅ |
| POLL-01 | KI-Verarbeitet-Filter in poll_new_docs.py | ✅ |
| DOC-01 | README Cron-Polling + Env-Var-Tabelle | ✅ |

## Noch offen (niedrige Priorität)

### P2 – HA-Konfiguration (Benutzeraktion erforderlich)
- [ ] `ha_url` setzen (oder env `HA_URL`)
- [ ] `ha_token` setzen: HA → Profil → Sicherheit → Langlebiger Token
- [ ] `ha_notify_target` setzen: z.B. `notify.mobile_app_iphone`
- [ ] `anthropic_api_key` setzen (API-Key Limit läuft ab 01.04.2026)

### P3 – Nice-to-have
- [ ] `requirements.txt` Versionen prüfen/aktualisieren

---

## Architektur

```
poll_new_docs.py  (Cron alle 5 min, fcntl.flock Process-Lock)
    └── auto_consume.py  (pro Dokument, via subprocess)
            ├── duplicate_check.py   (MD5 / SQLite WAL)
            ├── paperless_api.py     (REST API, JSON-Error-safe)
            ├── claude_namer.py      (2× Claude API)
            │       ├── Call 1: Tags-Kontext  → tags, person, firma, konfidenz
            │       └── Call 2── Dateinamen-Kontext → datum, kategorie, beschreibung
            └── ha_notify.py         (HA REST API, optional)
```

### Konfiguration
Secrets können per `config.yaml` **oder** Umgebungsvariable gesetzt werden:

| config.yaml-Feld | Env-Var | Pflicht |
|------------------|---------|---------|
| `paperless_url` | `PAPERLESS_URL` | ✅ |
| `paperless_token` | `PAPERLESS_TOKEN` | ✅ |
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | ✅ |
| `ha_url` | `HA_URL` | ❌ optional |
| `ha_token` | `HA_TOKEN` | ❌ optional |
| `ha_notify_target` | `HA_NOTIFY_TARGET` | ❌ optional |

### Dateien
| Datei | Beschreibung |
|-------|-------------|
| `auto_consume.py` | Haupt-Orchestrierung (Post-Consumption) |
| `claude_namer.py` | Claude API, 2 Prompts, Retry-Logik |
| `paperless_api.py` | Paperless REST Wrapper, JSON-safe |
| `duplicate_check.py` | MD5-Duplikat-Erkennung, SQLite WAL |
| `ha_notify.py` | HA-Benachrichtigungen (optional) |
| `poll_new_docs.py` | Cron-Polling + Vorschau + Process-Lock |
| `config.yaml` | Konfiguration (nicht in Git) |
| `.env.example` | Secrets-Template |
| `requirements.txt` | Python-Abhängigkeiten |

---

## Git-Branch
`claude/integrate-paperless-ai-gxaos`

Letzter Commit: `fix: production hardening – secrets, process-lock, error-handling`
