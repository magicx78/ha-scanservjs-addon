#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/common.sh"

scan_via_profile "image" "${1:-}" "${2:-}"
output_file="${BROTHER_LAST_OUTPUT_FILE:-}"
trigger_webhook "image" "BROTHER_TRIGGER_IMAGE_WEBHOOK_ID" "${1:-}" "${2:-}" "${output_file}"
