# scanservjs + KI (Paperless-AI)

Scanner Web-UI mit automatischer KI-Dokumentenklassifikation via Claude API und direkter Paperless-ngx Integration.

## Funktionsweise

1. **Scannen** – Dokument über die scanservjs Web-UI einscannen
2. **Ablegen** – Scan wird automatisch in das Paperless-ngx Eingangsverzeichnis kopiert
3. **KI-Klassifikation** – Claude analysiert das Dokument und vergibt Titel, Tags und Korrespondenten
4. **Fertig** – Dokument erscheint vollständig klassifiziert in Paperless-ngx

## Voraussetzungen

- [Paperless-ngx Addon](https://github.com/alexbelgium/hassio-addons) installiert und eingerichtet
- Anthropic API-Schlüssel (kostenlos unter [console.anthropic.com](https://console.anthropic.com))

## Einrichtung

### 1. API-Schlüssel konfigurieren

Trage deinen **Anthropic API-Schlüssel** in der Addon-Konfiguration ein.

### 2. Paperless-ngx verbinden

```
Paperless-ngx URL:   http://ca5234a0-paperless-ngx:8000
Paperless-ngx Token: <dein API-Token aus Paperless → Einstellungen → API-Token>
```

### 3. Scan-Ziel setzen

| Modus | Beschreibung |
|-------|-------------|
| `auto` | Erkennt `/share/paperless/consume` automatisch |
| `paperless` | Erzwingt Paperless-Consume-Verzeichnis |
| `custom` | Eigenes Verzeichnis (Feld „Wunschverzeichnis") |

### 4. Addon starten

Nach dem Start ist die Web-UI über **Öffnen** im Addon-Panel erreichbar.

## Brother Scanner

Für Brother-Scanner (MFC, DCP etc.) kann der integrierte brscan4-Treiber aktiviert werden:

1. **Brother-Unterstützung aktivieren** → `true`
2. **Brother-EULA akzeptieren** → `true`
3. **Modell und IP** eintragen
4. Addon neu starten

## Häufige Fragen

**Wie hoch sind die API-Kosten?**
Claude Haiku kostet ca. $0,001 pro Dokument – bei 100 Dokumenten/Monat unter $0,10.

**Welche Scanner werden unterstützt?**
Alle SANE-kompatiblen Scanner sowie Brother brscan4, HP, Epson, Canon und Xerox über AirScan (eSCL/WSD).

**Kann ich das Addon ohne KI nutzen?**
Ja – einfach den `anthropic_api_key` leer lassen. Das Addon funktioniert dann als normaler scanservjs-Scanner.

## Support & Quellcode

[github.com/magicx78/ha-scanservjs-addon](https://github.com/magicx78/ha-scanservjs-addon)
