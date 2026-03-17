# scanservjs + KI (Paperless-AI)

Scanner Web-UI mit automatischer KI-Dokumentenklassifikation via Claude API und direkter Paperless-ngx Integration.

## Einrichtung

**1. Anthropic API-Schlüssel** eintragen (von console.anthropic.com).

**2. Paperless-ngx verbinden:**
- Paperless-ngx URL, z.B. `http://ca5234a0-paperless-ngx:8000`
- API-Token aus Paperless-ngx unter Einstellungen

**3. Scan-Ziel wählen:**
- `auto` erkennt `/share/paperless/consume` automatisch
- `paperless` erzwingt das Paperless-Consume-Verzeichnis
- `custom` nutzt ein eigenes Verzeichnis

**4. Addon starten** – Web-UI über "Öffnen" im Panel erreichbar.

## Brother Scanner

Brother-Support (MFC, DCP) aktivieren:
1. "Brother-Unterstützung aktivieren" auf `true`
2. "Brother-EULA akzeptieren" auf `true`
3. Modell und IP eintragen
4. Addon neu starten

## Hinweise

Ohne `anthropic_api_key` funktioniert das Addon als normaler Scanner ohne KI.

Claude Haiku kostet ca. $0,001 pro Dokument.

## Support

https://github.com/magicx78/ha-scanservjs-addon
