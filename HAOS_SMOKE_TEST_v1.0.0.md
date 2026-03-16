# HAOS Smoke Test - ha-scanservjs-addon v1.0.0

Status: OPEN
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

Date:
HAOS version:
Supervisor version:
Architecture:

### Required checks

- Repository added: PASS / FAIL
- Add-on installed: PASS / FAIL
- Start without Brother support: PASS / FAIL
- Ingress / Web UI reachable: PASS / FAIL
- `scanimage -L` detects scanner: PASS / FAIL
- Test scan successful: PASS / FAIL
- OCR successful: PASS / FAIL

### Optional checks

- Brother support enabled: PASS / FAIL / N/A
- Real Brother device tested: PASS / FAIL / N/A
- Fallback without Brother re-verified: PASS / FAIL / N/A

### Overall result

- Go / No-Go:

### Notes

- 
