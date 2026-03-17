# PROGRESS.md – scanservjs-ai Addon Diagnose

**Branch:** `claude/integrate-paperless-ai-gxaos`
**Stand:** 2026-03-17
**Status:** 🔴 Addon startet nicht – mehrere Bugs identifiziert

---

## Diagnose: Warum startet das Addon nicht?

### 🔴 BUG 1 – KRITISCH: Falsches Claude-Modell-ID (API-Fehler beim ersten Scan)

**Datei:** `scanservjs-ai/scripts/claude_namer.py`
**Problem:** Das Modell `claude-haiku-4-5` existiert nicht. Die korrekte Model-ID lautet `claude-haiku-4-5-20251001`.
**Auswirkung:** Jeder API-Call an Claude schlägt mit `model_not_found` fehl → KI-Klassifikation crasht.

---

### 🔴 BUG 2 – KRITISCH: Config-Schema blockiert Addon-Start ohne API-Key

**Datei:** `scanservjs-ai/config.yaml`, Abschnitt `schema:`
**Problem:** Beide Felder sind als `str` (Pflichtfeld, nicht-optional) deklariert:
```yaml
schema:
  anthropic_api_key: str    # FEHLER: sollte str? sein
  paperless_token: str      # FEHLER: sollte str? sein
```
Die `options`-Defaults sind leere Strings `""`. HA Supervisor lehnt leere Pflichtfelder bei einigen Versionen ab.
**Auswirkung:** Das Addon kann nicht ohne eingetragenen API-Key starten.
**Fix:** `str` → `str?` (optionales Feld)

---

### 🟠 BUG 3 – HOCH: Python `int | None` Union-Syntax (Python 3.10+ erforderlich)

**Datei:** `scanservjs-ai/scripts/poll_new_docs.py`, Zeile ~89
**Problem:**
```python
def _get_ki_tag_id(...) -> int | None:  # Requires Python 3.10+
```
Das `sbs20/scanservjs:v3.0.3` Basis-Image enthält möglicherweise Python 3.9.
**Auswirkung:** `SyntaxError` beim Import → Cron-Job startet nicht.
**Fix:** `int | None` → `Optional[int]` (mit `from typing import Optional`)

---

### 🟠 BUG 4 – HOCH: `pip install --break-system-packages` kann fehlschlagen

**Datei:** `scanservjs-ai/Dockerfile`
**Problem:**
```dockerfile
RUN pip3 install --no-cache-dir --break-system-packages -r /opt/paperless-ai/requirements.txt
```
Der `--break-system-packages`-Flag wurde mit PEP 668 in neueren Debian-/pip-Versionen eingeführt. Auf dem `sbs20/scanservjs:v3.0.3` Basis-Image (Node.js-fokussiert) ist das Verhalten unsicher.
**Auswirkung:** Docker-Build schlägt fehl → Addon kann nicht gestartet werden.
**Fix:** Entweder `--break-system-packages` entfernen oder `python3-venv` + venv nutzen.

---

### 🟡 BUG 5 – MITTEL: Cron-Log-Verzeichnis möglicherweise nicht schreibbar

**Datei:** `scanservjs-ai/run.sh`, Funktion `start_ai_cron()`
**Problem:**
```bash
echo "*/5 * * * * root python3 /opt/paperless-ai/poll_new_docs.py >> /var/log/paperless-ai.log 2>&1"
```
Das Verzeichnis `/var/log/` existiert im Container, ist aber möglicherweise nicht schreibbar oder wird beim Neustart geleert.
**Fix:** Log nach `/data/paperless-ai.log` oder `/tmp/paperless-ai.log` umleiten (persistent: `/data/`).

---

### 🟡 BUG 6 – MITTEL: `auto_consume.py` schreibt Log in `/opt/paperless-ai/auto_consume.log`

**Datei:** `scanservjs-ai/scripts/auto_consume.py`
**Problem:** Log-Datei wird in `SCRIPT_DIR / "auto_consume.log"` = `/opt/paperless-ai/auto_consume.log` geschrieben. Das Verzeichnis ist Read-Only im laufenden Container (COPY-Layer).
**Fix:** Log-Pfad nach `/data/auto_consume.log` verschieben.

---

### 🟡 BUG 7 – MITTEL: `document_hashes.db` SQLite in `/opt/paperless-ai/` (nicht persistent)

**Datei:** `scanservjs-ai/scripts/duplicate_check.py` (referenziert in `auto_consume.py`)
**Problem:** Die SQLite-Datenbank für Duplikat-Erkennung liegt in `SCRIPT_DIR / "document_hashes.db"` = `/opt/paperless-ai/document_hashes.db`.
**Auswirkung:** Bei Addon-Neustart geht die gesamte Hash-Datenbank verloren → keine Duplikat-Erkennung nach Restart.
**Fix:** DB-Pfad nach `/data/document_hashes.db` verschieben.

---

## Zusammenfassung der Fixes

| # | Priorität | Datei | Problem | Fix |
|---|-----------|-------|---------|-----|
| 1 | 🔴 KRITISCH | `scripts/claude_namer.py` | Falsches Modell-ID | `claude-haiku-4-5` → `claude-haiku-4-5-20251001` |
| 2 | 🔴 KRITISCH | `config.yaml` schema | `str` statt `str?` | `anthropic_api_key: str?`, `paperless_token: str?` |
| 3 | 🟠 HOCH | `scripts/poll_new_docs.py` | `int \| None` Syntax | `Optional[int]` aus `typing` |
| 4 | 🟠 HOCH | `Dockerfile` | `--break-system-packages` | Flag entfernen oder venv nutzen |
| 5 | 🟡 MITTEL | `run.sh` | Log in `/var/log/` | → `/data/paperless-ai.log` |
| 6 | 🟡 MITTEL | `scripts/auto_consume.py` | Log in `/opt/` (read-only) | → `/data/auto_consume.log` |
| 7 | 🟡 MITTEL | `scripts/duplicate_check.py` | DB in `/opt/` (nicht persistent) | → `/data/document_hashes.db` |

---

## Status der Fixes

- [x] BUG 1 gefixt: `claude-haiku-4-5` → `claude-haiku-4-5-20251001`
- [x] BUG 2 gefixt: Schema `str` → `str?` für API-Keys
- [x] BUG 3 gefixt: `int | None` → `Optional[int]` (Python 3.9 compat)
- [x] BUG 4 gefixt: Dockerfile pip mit `||`-Fallback
- [x] BUG 5 gefixt: Cron-Log → `/data/paperless-ai.log`
- [x] BUG 6 gefixt: auto_consume Log → `/data/auto_consume.log`
- [x] BUG 7 gefixt: SQLite DB → `/data/document_hashes.db`
- [ ] Lokaler Test-Build (Docker)
- [ ] HA Supervisor Smoke-Test
