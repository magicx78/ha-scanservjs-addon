# Paperless-AI – KI-gestuetzte Dokumentenklassifikation

Automatisches Benennen, Kategorisieren und Taggen eingehender Scans
via **Claude API (claude-sonnet-4-6)** als Paperless-ngx Post-Consumption-Script.

```
JJJJ-MM-TT_Kategorie_Beschreibung_[Tag1][Tag2]...[Tag10]
```

---

## Setup (5 Schritte)

### 1. Dateien kopieren

Alle Dateien aus `paperless-ai/scripts/` in den Paperless-Addon-Container kopieren:

```
/config/scripts/
├── auto_consume.py
├── claude_namer.py
├── paperless_api.py
├── duplicate_check.py
├── ha_notify.py
├── config.yaml
└── requirements.txt
```

**Schnellweg via HA File-Editor oder Terminal:**
```bash
mkdir -p /config/scripts
cp paperless-ai/scripts/* /config/scripts/
chmod +x /config/scripts/auto_consume.py
```

### 2. Abhaengigkeiten installieren

Im Paperless-Addon-Container:
```bash
pip install -r /config/scripts/requirements.txt
```

> Hinweis: Im Paperless-HA-Addon-Container laeuft Python 3.11+.
> Falls `pip` nicht verfuegbar ist: `python3 -m ensurepip && python3 -m pip install ...`

### 3. Konfiguration anpassen

`/config/scripts/config.yaml` oeffnen und die Platzhalter ersetzen:

| Variable | Wo zu finden |
|---|---|
| `paperless_token` | Paperless -> Einstellungen -> API-Token |
| `anthropic_api_key` | https://console.anthropic.com |
| `ha_token` | HA -> Profil -> Sicherheit -> Token erstellen |
| `ha_notify_target` | z.B. `notify.mobile_app_iphone` |

### 4. Cron-Polling einrichten (empfohlen für HA-Addon)

Da `PAPERLESS_POST_CONSUME_SCRIPT` im HA-Addon-Betrieb nicht direkt konfigurierbar ist,
wird stattdessen ein Cron-Job genutzt:

```bash
# Crontab im Paperless-Addon-Container:
*/5 * * * * python3 /config/scripts/poll_new_docs.py >> /config/scripts/poll.log 2>&1
```

Das Script `poll_new_docs.py`:
- Pollt alle 5 Minuten auf neue, unkategorisierte Dokumente
- Zeigt eine Vorschau (Dokumente vorher/nachher)
- Verhindert parallele Läufe via `fcntl.flock` (Process-Lock)
- Filtert bereits mit `[KI-Verarbeitet]` getaggte Dokumente aus

**Alternativ** als direkter Post-Consume-Hook (falls Paperless-Umgebungsvariablen verfügbar):
```
PAPERLESS_POST_CONSUME_SCRIPT=/config/scripts/auto_consume.py
```

### 5. Konfiguration via Umgebungsvariablen (Secrets-safe)

Statt Tokens direkt in `config.yaml` zu schreiben, können Umgebungsvariablen gesetzt werden:

| Umgebungsvariable | config.yaml-Feld | Pflicht |
|-------------------|-----------------|---------|
| `PAPERLESS_URL` | `paperless_url` | ✅ |
| `PAPERLESS_TOKEN` | `paperless_token` | ✅ |
| `ANTHROPIC_API_KEY` | `anthropic_api_key` | ✅ |
| `HA_URL` | `ha_url` | optional |
| `HA_TOKEN` | `ha_token` | optional |
| `HA_NOTIFY_TARGET` | `ha_notify_target` | optional |

Umgebungsvariablen überschreiben immer die config.yaml-Werte.

### 6. Testen

Einen Scan einlegen oder eine PDF in den Consumption-Ordner legen.
Innerhalb von ~60 s sollte das Dokument in Paperless umbenannt
und auf dem Handy eine Benachrichtigung erscheinen.

Log pruefen:
```bash
tail -f /config/scripts/auto_consume.log
```

---

## Verzeichnis-Referenz

```
/config/scripts/
├── auto_consume.py       Haupt-Script (Einstiegspunkt fuer Paperless)
├── claude_namer.py       Claude API Wrapper + Prompt-Logik
├── paperless_api.py      Paperless REST API Wrapper
├── duplicate_check.py    MD5-Hash + SQLite Duplikat-Erkennung
├── ha_notify.py          Home Assistant Benachrichtigungen
├── config.yaml           Konfiguration (Tokens, URLs, Schwellenwerte)
├── requirements.txt      Python-Abhaengigkeiten
├── document_hashes.db    SQLite-Datenbank (auto-erstellt)
└── auto_consume.log      Rolling-Log (5 MB, 3 Backups)
```

---

## Dateinamenschema

```
JJJJ-MM-TT_Kategorie_Beschreibung_[Tag1]...[Tag10]
```

**Erlaubte Kategorien:**
`Haus | Arzt | Finanzamt | Krankenkasse | Lohnsteuer | Lohn | Sozialversicherung | Rechnung | Arbeit | Sonstiges`

**Beispiele:**
```
2024-08-13_Finanzamt_Detmold-Umsatzsteuer-Abrechnung-2023_[Finanzamt][Detmold][Umsatzsteuer][2023][Wiesbrock-GbR]
2025-03-19_Krankenkasse_BKK-Krankengeld-Ende-AU_[Krankenkasse][Versicherung][BKK][Krankengeld][Wiesbrock]
2024-01-00_Lohn_Bauhaus-Verdienstabrechnung-Januar-2024_[Lohn][Bauhaus][Maike-Wiesbrock][Sparkasse]
0000-00-00_Sonstiges_Rezept-Vanillekuchen_[Rezepte][Backen][Vanillekuchen]
```

---

## Pflicht-Tags je Dokumenttyp

| Dokumenttyp | Pflicht-Tags |
|---|---|
| Lohn / Lohnsteuer | `[Sparkasse]` |
| Kranken- / Sozialversicherung | `[Versicherung]` |
| Rezepte | `[Rezepte]` |
| Haus-Bauakten (Hollmann) | `[Hollmann][Helpup]` |

---

## Troubleshooting

**Script wird nicht ausgefuehrt**
- Pruefen ob `PAPERLESS_POST_CONSUME_SCRIPT` korrekt gesetzt ist
- Ausfuehrungsrechte: `chmod +x /config/scripts/auto_consume.py`
- Shebang pruefen: erste Zeile muss `#!/usr/bin/env python3` sein

**`ModuleNotFoundError: anthropic`**
```bash
pip install -r /config/scripts/requirements.txt
```

**Dokument bleibt unbenannt, kein Eintrag im Log**
- Paperless-Addon-Container neu starten
- `PAPERLESS_POST_CONSUME_SCRIPT`-Pfad exakt pruefen (kein Trailing-Space)

**`401 Unauthorized` von Paperless**
- `paperless_token` in `config.yaml` pruefen
- Token in Paperless neu generieren: Einstellungen -> API-Token

**`401 Unauthorized` von Home Assistant**
- `ha_token` abgelaufen oder falsch – neues Long-Lived-Token erstellen

**Konfidenz immer unter 0.7**
- OCR-Qualitaet pruefen (Tesseract deu+eng aktiviert?)
- `min_konfidenz` in `config.yaml` ggf. auf `0.5` senken

**Duplikat-Datenbank zuruecksetzen**
```bash
rm /config/scripts/document_hashes.db
```
Die DB wird beim naechsten Scan automatisch neu angelegt.
