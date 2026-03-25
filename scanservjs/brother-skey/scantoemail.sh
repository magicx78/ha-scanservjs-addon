#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

# Wenn ein Multi-Page-Scan laeuft und auf naechste Seite wartet:
# Signal senden statt neuen Scan starten
if [[ -f /tmp/brother_scan_waiting ]]; then
  touch /tmp/brother_scan_continue
  button_log "info" "continue signal sent for multipage scan (email)"
  exit 0
fi

scan_via_profile "email" "${1:-}" "${2:-}"
