# Forum Post Vorlage (HA Community, kurz)

## Titel

`[Unofficial Add-on] scanservjs + Brother Frontpanel + Paperless (v1.0.13 / r29)`

## Beitrag

Kurzes Community-Feedback zu meinem Setup mit `ha-scanservjs-addon`.

Teststand:

- Add-on: `v1.0.13`
- Runtime: `2026-03-16-r29`
- HAOS: `<deine HAOS Version>`
- Scanner: `<dein Modell>`

Bei mir laeuft:

- `Starte scanservjs` im Log
- `/api/v1/context` liefert Scanner
- Web/API-Scan funktioniert
- Brother Frontpanel: File/Email/Image/OCR funktioniert

Repo:

- [https://github.com/magicx78/ha-scanservjs-addon](https://github.com/magicx78/ha-scanservjs-addon)

Kurz-Troubleshooting:

1. Add-on neu starten und Log auf Runtime-Revision pruefen.
2. `/api/v1/context` testen.
3. Falls Scanner fehlt: `airscan_devices` pruefen oder `generic_scanner_ip` setzen.
4. Bei Brother: EULA akzeptieren, `brsaneconfig4 -q` pruefen, IP/Nodename kontrollieren.

Disclaimer:

`Unofficial community add-on. Not affiliated with Home Assistant or Brother.`
