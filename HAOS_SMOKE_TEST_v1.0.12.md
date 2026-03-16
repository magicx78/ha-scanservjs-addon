# HAOS Smoke Test - ha-scanservjs-addon v1.0.12

Status: GO  
Release gate: Passed

## Test record

Date: 2026-03-16  
Architecture: amd64  
Addon version: 1.0.12  
Runtime revision: 2026-03-16-r28

## Required checks

- Repository added: PASS
- Add-on installed/updated: PASS
- Add-on starts without restart loop: PASS
- Log reaches `Starte scanservjs`: PASS
- `/api/v1/context` works: PASS
- Brother device in context (`brother4:net1;dev0`): PASS
- Web/API scan works: PASS
- Brother frontpanel `Scan to File`: PASS
- Brother frontpanel `Scan to Email`: PASS
- Brother frontpanel `Scan to Image`: PASS
- Brother frontpanel `Scan to OCR`: PASS

## Generic fallback checks

- New option `generic_scanner_ip` available in add-on config: PASS
- Startup fallback order is backward compatible (`generic_scanner_ip` -> `brother_scanner_ip`): PASS
- Existing Brother flow unaffected by fallback extension: PASS

## Notes

- One startup warning can appear once on fresh runtime state:
  - `scanimage -L fehlgeschlagen: Created directory: /var/lib/snmp/cert_indexes`
  - This did not block startup or API/device context.
- This file is the final validation baseline for `v1.0.12` (`r28`).
