#!/usr/bin/env bash

BROTHER_BUTTON_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BROTHER_BUTTON_ENV_FILE="${BROTHER_BUTTON_SCRIPT_DIR}/scanservjs.env"
BROTHER_BUTTON_LOG_FILE="/tmp/scanservjs-brother-button.log"

button_log() {
  local level="$1"
  shift
  local line

  line="[Brother Button][${level}] $(date '+%Y-%m-%d %H:%M:%S') $*"
  printf '%s\n' "${line}" >>"${BROTHER_BUTTON_LOG_FILE}" 2>/dev/null || true

  if [[ -w /proc/1/fd/1 ]]; then
    printf '%s\n' "${line}" >/proc/1/fd/1
  else
    printf '%s\n' "${line}" >&2
  fi
}

load_button_env() {
  if [[ ! -f "${BROTHER_BUTTON_ENV_FILE}" ]]; then
    button_log "warn" "env file missing: ${BROTHER_BUTTON_ENV_FILE}"
    return 0
  fi

  set -a
  # shellcheck disable=SC1090
  source "${BROTHER_BUTTON_ENV_FILE}"
  set +a
  button_log "info" "loaded env file: ${BROTHER_BUTTON_ENV_FILE}"
}

button_timestamp() {
  date '+%Y-%m-%d_%H-%M-%S'
}

button_output_dir() {
  printf '/data/output\n'
}

button_profile_config_path() {
  local profile="$1"
  local config_name=""

  case "$profile" in
    file)
      config_name="scantofile.config"
      ;;
    email)
      config_name="scantoemail.config"
      ;;
    image)
      config_name="scantoimage.config"
      ;;
    ocr)
      config_name="scantoocr.config"
      ;;
  esac

  [[ -n "${config_name}" ]] || return 1

  if [[ -f "/etc/opt/brother/scanner/brscan-skey/${config_name}" ]]; then
    printf "/etc/opt/brother/scanner/brscan-skey/%s\n" "${config_name}"
    return 0
  fi

  if [[ -f "/opt/brother/scanner/brscan-skey/${config_name}" ]]; then
    printf "/opt/brother/scanner/brscan-skey/%s\n" "${config_name}"
    return 0
  fi

  return 1
}

load_button_profile_config() {
  local profile="$1"
  local config_path=""

  if ! config_path="$(button_profile_config_path "${profile}")"; then
    button_log "warn" "no profile config found for profile=${profile}"
    return 0
  fi

  # shellcheck disable=SC1090
  source "${config_path}"
  button_log "info" "loaded profile config: ${config_path}"
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

append_skey_args() {
  local profile="$1"
  local -n args_ref="$2"

  load_button_profile_config "${profile}"

  if [[ -n "${resolution:-}" ]]; then
    args_ref+=("--resolution" "${resolution}")
  else
    args_ref+=("--resolution" "100")
  fi

  if [[ -n "${source:-}" ]]; then
    args_ref+=("--source" "${source}")
  else
    args_ref+=("--source" "FB")
  fi

  if [[ -n "${size:-}" ]]; then
    args_ref+=("--size" "${size}")
  else
    args_ref+=("--size" "A4")
  fi

  if [[ "${duplex:-OFF}" == "ON" ]]; then
    args_ref+=("--duplex")
  fi
}

copy_scan_output() {
  local output_file="$1"

  if [[ -z "${COPY_SCANS_TO:-}" || "${COPY_SCANS_TO}" == "null" ]]; then
    button_log "info" "copy skipped for ${output_file}: COPY_SCANS_TO not set"
    return 0
  fi

  mkdir -p "${COPY_SCANS_TO}" 2>/dev/null || true
  if ! cp -f "${output_file}" "${COPY_SCANS_TO}/"; then
    button_log "error" "copy failed target=${COPY_SCANS_TO} file=${output_file}"
    return 1
  fi

  button_log "info" "copied output to ${COPY_SCANS_TO}/$(basename "${output_file}")"
}

scan_via_profile() {
  local profile="$1"
  local requested_device="${2:-}"
  local friendly_name="${3:-}"
  local device format ext output_dir output_file
  local skey_bin=""
  local -a scan_args=()

  button_log "info" "scan invoked profile=${profile} requested_device=${requested_device:-<leer>} friendly_name=${friendly_name:-<leer>}"
  load_button_env

  output_dir="$(button_output_dir)"
  mkdir -p "${output_dir}"
  button_log "info" "using output dir: ${output_dir}"

  device="$(resolve_device "${requested_device}")"
  if [[ -z "${device}" ]]; then
    button_log "error" "no scanner device resolved for profile=${profile}"
    exit 1
  fi
  button_log "info" "resolved device: ${device}"

  if [[ -x "/opt/brother/scanner/brscan-skey/skey-scanimage" ]]; then
    skey_bin="/opt/brother/scanner/brscan-skey/skey-scanimage"
    format="tiff"
    ext="tif"
    output_file="${output_dir}/button_${profile}_$(button_timestamp).${ext}"
    scan_args=(--device-name "${device}" --outputfile "${output_file}")
    append_skey_args "${profile}" scan_args
    button_log "info" "skey scan start profile=${profile} output=${output_file} args=${scan_args[*]}"
    if "${skey_bin}" "${scan_args[@]}"; then
      button_log "info" "skey-scanimage finished successfully profile=${profile}"
    else
      local exit_code=$?
      rm -f "${output_file}"
      button_log "error" "skey-scanimage failed profile=${profile} exit=${exit_code}"
      exit 1
    fi
  else
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

    button_log "info" "generic scan start profile=${profile} output=${output_file} args=${scan_args[*]}"
    if scanimage "${scan_args[@]}" >"${output_file}"; then
      button_log "info" "generic scan finished successfully profile=${profile}"
    else
      local exit_code=$?
      rm -f "${output_file}"
      button_log "error" "scanimage failed profile=${profile} exit=${exit_code}"
      exit 1
    fi
  fi

  if [[ ! -s "${output_file}" ]]; then
    rm -f "${output_file}"
    button_log "error" "empty output file profile=${profile} output=${output_file}"
    exit 1
  fi

  button_log "info" "scan output created profile=${profile} output=${output_file} size=$(wc -c <"${output_file}" 2>/dev/null || printf '0')"
  copy_scan_output "${output_file}"
  button_log "info" "scan saved profile=${profile} output=${output_file}"
}

trigger_webhook() {
  local button="$1"
  local webhook_var="$2"
  local requested_device="${3:-}"
  local friendly_name="${4:-}"
  local webhook_id device payload timestamp

  button_log "info" "trigger invoked button=${button} requested_device=${requested_device:-<leer>} friendly_name=${friendly_name:-<leer>}"
  load_button_env

  webhook_id="${!webhook_var:-}"
  if [[ -z "${webhook_id}" || "${webhook_id}" == "null" ]]; then
    button_log "warn" "no webhook configured for button=${button}"
    return 0
  fi

  if [[ -z "${SUPERVISOR_TOKEN:-}" ]]; then
    button_log "error" "SUPERVISOR_TOKEN missing for button=${button}"
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

  button_log "info" "trigger webhook start button=${button} webhook_id=${webhook_id} device=${device}"
  curl -fsS \
    -X POST \
    -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    "http://supervisor/core/api/webhook/${webhook_id}" >/dev/null
  button_log "info" "webhook delivered button=${button} webhook_id=${webhook_id}"
}
