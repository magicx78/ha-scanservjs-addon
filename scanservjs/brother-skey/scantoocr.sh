#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# Wenn ein Multi-Page-Scan laeuft und auf naechste Seite wartet:
# Signal senden statt neuen Scan starten
if [[ -f /tmp/brother_scan_waiting ]]; then
  touch /tmp/brother_scan_continue
  button_log "info" "continue signal sent for multipage scan (ocr)"
  exit 0
fi

scan_via_profile "ocr" "${1:-}" "${2:-}"
output_file="${BROTHER_LAST_OUTPUT_FILE:-}"
trigger_webhook "ocr" "BROTHER_TRIGGER_OCR_WEBHOOK_ID" "${1:-}" "${2:-}" "${output_file}"
