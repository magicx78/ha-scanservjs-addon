#!/usr/bin/env bash

BROTHER_BUTTON_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BROTHER_BUTTON_ENV_FILE="${BROTHER_BUTTON_SCRIPT_DIR}/scanservjs.env"

load_button_env() {
  [[ -f "${BROTHER_BUTTON_ENV_FILE}" ]] || return 0

  set -a
  # shellcheck disable=SC1090
  source "${BROTHER_BUTTON_ENV_FILE}"
  set +a
}

button_timestamp() {
  date '+%Y-%m-%d_%H-%M-%S'
}

button_output_dir() {
  printf '/data/output\n'
}

normalize_scan_format() {
  case "$1" in
    jpg)
      printf 'jpeg\n'
      ;;
    tif)
      printf 'tiff\n'
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

scan_extension() {
  case "$1" in
    jpeg)
      printf 'jpg\n'
      ;;
    tiff)
      printf 'tif\n'
      ;;
    *)
      printf '%s\n' "$1"
      ;;
  esac
}

discover_first_device() {
  scanimage -L 2>/dev/null | sed -n "s/^device '\\([^']*\\)'.*/\\1/p" | head -n 1
}

resolve_device() {
  local requested="${1:-}"

  if [[ -n "${requested}" && "${requested}" != "null" ]]; then
    printf '%s\n' "${requested}"
    return 0
  fi

  if [[ -n "${BROTHER_DEFAULT_DEVICE:-}" && "${BROTHER_DEFAULT_DEVICE}" != "null" ]]; then
    printf '%s\n' "${BROTHER_DEFAULT_DEVICE}"
    return 0
  fi

  discover_first_device
}

append_scan_args() {
  local extra="$1"
  local -n args_ref="$2"
  local -a parsed=()

  [[ -n "${extra}" ]] || return 0

  read -r -a parsed <<<"${extra}"
  [[ "${#parsed[@]}" -gt 0 ]] && args_ref+=("${parsed[@]}")
}

copy_scan_output() {
  local output_file="$1"

  if [[ -z "${COPY_SCANS_TO:-}" || "${COPY_SCANS_TO}" == "null" ]]; then
    return 0
  fi

  mkdir -p "${COPY_SCANS_TO}" 2>/dev/null || true
  if ! cp -f "${output_file}" "${COPY_SCANS_TO}/"; then
    echo "Brother button: copy to ${COPY_SCANS_TO} failed for ${output_file}" >&2
  fi
}

scan_via_profile() {
  local profile="$1"
  local requested_device="${2:-}"
  local friendly_name="${3:-}"
  local device format ext output_dir output_file
  local -a scan_args=()

  load_button_env

  output_dir="$(button_output_dir)"
  mkdir -p "${output_dir}"

  device="$(resolve_device "${requested_device}")"
  if [[ -z "${device}" ]]; then
    echo "Brother button ${profile}: no scanner device resolved" >&2
    exit 1
  fi

  format="$(normalize_scan_format "${BROTHER_BUTTON_SCAN_FORMAT:-jpeg}")"
  ext="$(scan_extension "${format}")"
  output_file="${output_dir}/button_${profile}_$(button_timestamp).${ext}"

  scan_args=(--device-name="${device}" --format="${format}")
  case "${profile}" in
    file)
      append_scan_args "${BROTHER_BUTTON_SCAN_ARGS_FILE:-}" scan_args
      ;;
    email)
      append_scan_args "${BROTHER_BUTTON_SCAN_ARGS_EMAIL:-}" scan_args
      ;;
  esac

  echo "Brother button ${profile}: scan start device=${device} name=${friendly_name:-<unknown>} output=${output_file}"
  if ! scanimage "${scan_args[@]}" >"${output_file}"; then
    rm -f "${output_file}"
    echo "Brother button ${profile}: scanimage failed" >&2
    exit 1
  fi

  if [[ ! -s "${output_file}" ]]; then
    rm -f "${output_file}"
    echo "Brother button ${profile}: empty output file" >&2
    exit 1
  fi

  copy_scan_output "${output_file}"
  echo "Brother button ${profile}: scan saved to ${output_file}"
}

trigger_webhook() {
  local button="$1"
  local webhook_var="$2"
  local requested_device="${3:-}"
  local friendly_name="${4:-}"
  local webhook_id device payload timestamp

  load_button_env

  webhook_id="${!webhook_var:-}"
  if [[ -z "${webhook_id}" || "${webhook_id}" == "null" ]]; then
    echo "Brother button ${button}: no webhook configured"
    return 0
  fi

  if [[ -z "${SUPERVISOR_TOKEN:-}" ]]; then
    echo "Brother button ${button}: SUPERVISOR_TOKEN missing" >&2
    exit 1
  fi

  device="$(resolve_device "${requested_device}")"
  timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  payload="$(jq -nc \
    --arg source 'scanservjs_brother_frontpanel' \
    --arg button "${button}" \
    --arg device "${device}" \
    --arg scanner_name "${BROTHER_SCANNER_NAME:-}" \
    --arg friendly_name "${friendly_name}" \
    --arg timestamp "${timestamp}" \
    '{source:$source,button:$button,device:$device,scanner_name:$scanner_name,friendly_name:$friendly_name,timestamp:$timestamp}')"

  echo "Brother button ${button}: trigger webhook ${webhook_id}"
  curl -fsS \
    -X POST \
    -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    "http://supervisor/core/api/webhook/${webhook_id}" >/dev/null
  echo "Brother button ${button}: webhook delivered"
}
