# PROGRESS.md – scanservjs-AI Addon

**Repo:** https://github.com/magicx78/ha-scanservjs-addon
**Branch:** `main`
**Aktuelle Version:** `1.2.7`
**Stand:** 2026-03-17

---

## Status: Stabil & laufend ✅

Das Addon baut erfolgreich, startet und läuft auf Home Assistant OS.
Scanner (Brother MFC-L2700DW, 10.10.10.216) wird erkannt und ist aktiv.

---

## Was läuft

| Komponente | Status |
|-----------|--------|
| Docker Build v1.2.7 | ✅ Erfolgreich |
| scanservjs Web-UI (Port 8080) | ✅ Läuft |
| Brother MFC-L2700DW (`brother4:net1;dev0`) | ✅ Erkannt |
| brscan4 + brscan-skey Installation | ✅ Pro Start |
| KI-Konfiguration (`/opt/paperless-ai/config.yaml`) | ✅ Wird geschrieben |
| Paperless-AI Cron (alle 5 Min) | ✅ Gestartet |
| COPY_SCANS_TO → `/share/paperless/consume` | ✅ Konfiguriert |
| Claude.ai Theme (CSS) | ✅ Injiziert |
| KI Sidebar-Panels (JS) | ✅ Injiziert |

---

## Alle Fixes (Verlauf)

| Version | Commit | Was |
|---------|--------|-----|
| 1.2.2 | `f06f28e` | 7 Stability-Fixes: falsches Modell, Schema, Python 3.9 compat, PEP 668 venv, Logs nach /data/, KeyError, Cron-Pfad |
| 1.2.2 | `b8b8542` | Port 8080, Token aus Git entfernt |
| 1.2.2 | `84eaaa0` | `config.example.yaml` → `config.yaml.example` (HA Warning behoben) |
| 1.2.3 | `2c839ce` | Claude-inspired CSS Theme, Dockerfile-Injection |
| 1.2.4 | `57ff47f` | Docker-Cache-Bust: `python3-venv` in apt-get Text → Cache-Miss erzwungen |
| 1.2.5 | `9f0caf6` | `brother_copy_ocr_to_target: true` — Hardware-Button-Scans gehen jetzt nach Paperless |
| 1.2.6 | `2b56775` | UI komplett auf claude.ai Layout umgestellt: dunkle Sidebar, warme Content-Area, Inter-Font |
| 1.2.7 | `d0ed38a` | KI Kontext-Panels in Sidebar: "Bezug / Dateiname" + "Tags" live nach KI-Klassifikation |

---

## Architektur

```
[Brother Scanner MFC-L2700DW]
       │  USB / Netzwerk (10.10.10.216)
       ▼
[scanservjs Web-UI :8080]
  ├── afterScan-Hook → /share/paperless/consume/
  └── Brother-Button-Skripte (brscan-skey)
           └── OCR/File → /share/paperless/consume/
                              │
                              ▼
                    [Paperless-ngx Consumer]
                    erstellt Dokument (kein document_type)
                              │
                              ▼
                    [poll_new_docs.py — Cron alle 5 Min]
                    findet Dokumente ohne document_type
                              │
                              ▼
                    [auto_consume.py]
                    ├── OCR-Text holen (Paperless API)
                    ├── Claude Haiku 4.5 → klassifiziert
                    ├── Titel / Tags / Typ in Paperless setzen
                    ├── Tag "KI-Verarbeitet" setzen
                    ├── ki-status.json schreiben → UI-Panels
                    └── HA-Benachrichtigung senden
```

---

## Dateien

```
scanservjs-ai/
├── Dockerfile              # venv, custom.css+js injection, port 8080
├── config.yaml             # v1.2.7, schema alle str?, brother_copy_ocr_to_target: true
├── run.sh                  # r35: write_ai_config, start_ai_cron, venv-Cron
├── custom.css              # claude.ai Theme: dunkle Sidebar, warme Content-Area
├── custom.js               # KI-Panels: polling /ki-status.json alle 30s
├── config.local.js         # afterScan-Hook → COPY_SCANS_TO
├── build.yaml              # amd64: sbs20/scanservjs:v3.0.3
└── scripts/
    ├── auto_consume.py     # KI-Pipeline + schreibt ki-status.json
    ├── poll_new_docs.py    # Cron-Poller (Paperless API)
    ├── claude_namer.py     # Claude Haiku 4.5 (claude-haiku-4-5-20251001)
    ├── paperless_api.py    # Paperless REST API wrapper
    ├── ha_notify.py        # HA persistent_notification
    ├── duplicate_check.py  # MD5-Hash DB (/data/document_hashes.db)
    └── requirements.txt    # anthropic>=0.44.0, requests, pyyaml, etc.
```

---

## Offene Punkte

| # | Was | Priorität |
|---|-----|-----------|
| 1 | End-to-End Test: Web-UI Scan → Paperless → KI → Panels | 🔴 HOCH |
| 2 | `/data/paperless-ai.log` nach Scan prüfen (KI läuft durch?) | 🟡 MITTEL |
| 3 | KI Sidebar-Panels sichtbar nach Update auf v1.2.7? | 🟡 MITTEL |
| 4 | brother_copy_ocr_to_target in bestehender Installation auf true setzen | 🟡 MITTEL |

---

## Bekannte Eigenheiten

- `scanimage -L fehlgeschlagen` beim Start → **Normal**, Brother ist per `brsaneconfig4` direkt registriert, nicht über scanimage-Discovery
- brscan-skey Prozess-Check "uneindeutig" → **Normal**, Frontpanel funktioniert trotzdem
- brscan4 wird bei jedem Container-Start frisch installiert (apt-get) → dauert ~10 Sek extra beim Start
- KI-Panels nur auf Screens ≥ 1264px sichtbar (kleinere Screens: ausgeblendet)

---

## Nächste Schritte

1. **Update auf v1.2.7** in HA (Settings → Add-ons → Update)
2. **Test**: Scan über Web-UI → Pipeline prüfen
3. **Prüfen**: `brother_copy_ocr_to_target: true` in Addon-Konfiguration gesetzt?
4. **Log lesen**: `/data/paperless-ai.log` nach erstem Scan
