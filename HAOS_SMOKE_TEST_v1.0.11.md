# HAOS Smoke Test - ha-scanservjs-addon v1.0.11

Status: GO
Release gate: Passed

## Test record

Date: 2026-03-16  
Architecture: amd64  
Addon version: 1.0.11  
Runtime revision: 2026-03-16-r27

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

## Storage/routing checks

- `File` copied to configured target (`copy_scans_to`): PASS
- `Image/OCR` can remain in scanservjs Files tab (per `brother_copy_*_to_target`): PASS
- Paperless ingest compatibility for Brother TIFF target copies: PASS (conversion path active)

## Notes

- Legacy `v1.0.0` smoke report remains historical and was intentionally left unchanged.
- This file is the final validation baseline for the Brother frontpanel fix line.
