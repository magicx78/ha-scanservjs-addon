# HAOS Smoke Test - ha-scanservjs-addon v1.0.0

Status: NO-GO
Release gate: Required before tagging `v1.0.0`

## Practical step sequence

1. In HAOS, add the custom add-on repository:
   `https://github.com/magicx78/ha-scanservjs-addon`
2. Install the `scanservjs` add-on.
3. Keep Brother support disabled.
4. Start the add-on and verify it stays running.
5. Open the Ingress / Web UI.
6. Run `scanimage -L` and verify a generic SANE scanner is detected.
7. Perform one test scan.
8. Trigger OCR and verify the result.
9. Record the outcome below.
10. Only if all required checks are `PASS`: release is `Go`.

## Test record

Date: 2026-03-16
HAOS version:
Supervisor version:
Architecture: amd64

### Required checks

- Repository added: PASS
- Add-on installed: PASS
- Start without Brother support: PASS
- Ingress / Web UI reachable: PASS
- `scanimage -L` detects scanner: FAIL
- Test scan successful: FAIL
- OCR successful: FAIL

### Optional checks

- Brother support enabled: PASS
- Real Brother device tested: PASS
- Fallback without Brother re-verified: PASS

### Overall result

- Go / No-Go: No-Go

### Notes

- Add-on starts under HAOS and the Web UI is reachable.
- Generic SANE/AirScan detection did not expose a scanner in scanservjs.
- Optional Brother runtime installed and registered brscan4 successfully, but no scan device was returned to the UI.
- Release remains blocked until a scanner is detected and a real test scan succeeds.
