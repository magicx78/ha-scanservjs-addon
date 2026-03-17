# PROGRESS.md – scanservjs-ai Addon

**Branch:** `main`
**Stand:** 2026-03-17 | **Runtime-Revision:** 2026-03-17-r31
**Addon-Version:** 1.2.3

---

## Aktueller Status

### ✅ Alle Code-Fixes committed (v1.2.3 auf `main`)

| # | Fix | Datei |
|---|-----|-------|
| 1 | Falsches Modell `claude-haiku-4-5` → `claude-haiku-4-5-20251001` | `scripts/claude_namer.py` |
| 2 | Schema `str` → `str?` (optionale Felder) | `config.yaml` |
| 3 | `int\|None` → `Optional[int]` (Python 3.9 compat) | `scripts/poll_new_docs.py` |
| 4 | PEP 668 pip geblockt → `python3 -m venv /opt/venv` | `Dockerfile` |
| 5 | Logs/DB in read-only `/opt/` → `/data/` | `auto_consume.py`, `run.sh` |
| 6 | `config["key"]` KeyError → `.get("key")` | `poll_new_docs.py` |
| 7 | Port 8181 → 8080 | `config.yaml`, `Dockerfile` |
| 8 | Echter Token aus Git entfernt | `paperless-ai/scripts/config.yaml` |
| 9 | `config.example.yaml` → `config.yaml.example` | HA-Warning behoben |
| 10 | Claude-inspired CSS Theme + Dockerfile-Injection | `custom.css`, `Dockerfile` |
| 11 | Cron nutzt `/opt/venv/bin/python3` explizit | `run.sh` |

---

## 🔴 AKTIVER BLOCKER: Docker Build-Cache auf HA-Host

### Symptom (aus Supervisor-Logs)
```
#6 [ 2/10] RUN apt-get update ... python3 python3-pip cron ...
#6 CACHED   ← ALTE LAYER ohne python3-venv !!!
#9 [ 5/10] RUN pip3 install --no-cache-dir ...
#9 ERROR: externally-managed-environment   ← PEP 668
io.hass.version=1.2.0   ← HA liest alten config.yaml aus Cache
```

### Ursache
HA baut noch immer **v1.2.0** mit **altem Dockerfile** (ohne `python3-venv`).
Docker-Layer-Cache auf dem HA-Host ignoriert neue Git-Commits.

### Lösung (USER ACTION REQUIRED)
```bash
# 1. SSH in Home Assistant
ssh root@homeassistant.local

# 2. Docker-Cache komplett löschen
docker builder prune --all --force

# 3. In HA UI:
#    Settings → Add-ons → scanservjs KI → Uninstall
#    → Repository neu hinzufügen → Addon neu installieren
```

### Erfolgskriterien nach Rebuild
```
io.hass.version=1.2.3           ← Neue Version
#6 RUN apt-get ... python3-venv  ← Neue Layer, KEIN "CACHED"
#9 RUN python3 -m venv           ← Venv wird erstellt
Container startet ohne ERROR
```

---

## 🟡 OFFEN: Scans landen nicht in Paperless-ngx

**User bestätigt:** Scans erscheinen NICHT in Paperless.
**Konfiguration:** `copy_scans_to_mode=custom`, Pfad `/share/paperless/consume`

**Untersuchung steht aus** (erst nach BLOCKER 1 möglich):
- Feuert `afterScan`-Hook in `config.local.js`?
- Wird `/share/paperless/consume` korrekt gemountet?
- Sieht Paperless-ngx Dateien in `consume`-Verzeichnis?

---

## Datei-Übersicht

```
scanservjs-ai/
├── Dockerfile              # v1.2.3: venv, custom.css injection, port 8080
├── config.yaml             # v1.2.3, ingress_port 8080, alle schema str?
├── run.sh                  # r31: write_ai_config, start_ai_cron, venv cron
├── custom.css              # Claude-Theme (orange #d97757, brown #3d2b1f)
├── config.local.js         # scanservjs config (afterScan → COPY_SCANS_TO)
└── scripts/
    ├── auto_consume.py     # KI-Pipeline: OCR → Claude → Paperless
    ├── poll_new_docs.py    # Pollt Paperless alle 5min
    ├── claude_namer.py     # Claude Haiku 4.5 API
    ├── paperless_api.py    # Paperless REST API wrapper
    ├── ha_notify.py        # HA Notifications
    ├── duplicate_check.py  # MD5-Hash Duplikat-Erkennung (DB: /data/)
    └── requirements.txt    # anthropic>=0.44.0, requests, pyyaml, etc.
```

---

## Nächste Schritte

1. **[USER]** `docker builder prune --all --force` auf HA-Host
2. **[USER]** Addon in HA neu installieren
3. **[VERIFY]** Build-Log: v1.2.3 ohne CACHED apt-get Layer
4. **[VERIFY]** Test-Scan → `/share/paperless/consume` prüfen
5. **[VERIFY]** `/data/paperless-ai.log` auf KI-Klassifikation prüfen
6. **[VERIFY]** Claude-Theme im scanservjs UI sichtbar
