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
}

button_timestamp() {
  date '+%Y-%m-%d_%H-%M-%S'
}

button_output_dir() {
  if [[ -n "${BROTHER_BUTTON_OUTPUT_DIR:-}" && "${BROTHER_BUTTON_OUTPUT_DIR}" != "null" ]]; then
    printf '%s\n' "${BROTHER_BUTTON_OUTPUT_DIR}"
  else
    printf '/data/output\n'
  fi
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
    args_ref+=("--resolution" "${BROTHER_BUTTON_DEFAULT_RESOLUTION:-300}")
  fi

  if [[ -n "${source:-}" ]]; then
    args_ref+=("--source" "${source}")
  else
    args_ref+=("--source" "${BROTHER_SCAN_SOURCE:-FB}")
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

paperless_target_enabled() {
  [[ "${COPY_SCANS_TO:-}" == /share/paperless* ]]
}

copy_to_target_enabled_for_profile() {
  local profile="$1"

  case "$profile" in
    file)
      [[ "${BROTHER_COPY_FILE_TO_TARGET:-true}" == "true" ]]
      ;;
    email)
      [[ "${BROTHER_COPY_EMAIL_TO_TARGET:-true}" == "true" ]]
      ;;
    image)
      [[ "${BROTHER_COPY_IMAGE_TO_TARGET:-false}" == "true" ]]
      ;;
    ocr)
      [[ "${BROTHER_COPY_OCR_TO_TARGET:-false}" == "true" ]]
      ;;
    *)
      return 0
      ;;
  esac
}

normalize_profile_output_format() {
  local profile="$1"
  local format="native"

  case "$profile" in
    image)
      format="${BROTHER_IMAGE_OUTPUT_FORMAT:-jpg}"
      ;;
    ocr)
      format="${BROTHER_OCR_OUTPUT_FORMAT:-pdf}"
      ;;
    *)
      format="native"
      ;;
  esac

  format="$(printf '%s' "$format" | tr '[:upper:]' '[:lower:]')"
  case "$format" in
    native|jpg|jpeg|pdf|tif|tiff)
      ;;
    *)
      button_log "warn" "unknown output format for profile=${profile}: ${format}. fallback=native"
      format="native"
      ;;
  esac

  case "$format" in
    jpg)
      format="jpeg"
      ;;
    tif)
      format="tiff"
      ;;
  esac

  printf '%s\n' "$format"
}

convert_profile_output() {
  local profile="$1"
  local output_file="$2"
  local target_format converted_file ext

  ext="${output_file##*.}"
  ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"

  target_format="$(normalize_profile_output_format "$profile")"
  case "$target_format" in
    native|tiff)
      printf '%s\n' "$output_file"
      return 0
      ;;
    jpeg)
      if [[ "$ext" == "jpg" || "$ext" == "jpeg" ]]; then
        printf '%s\n' "$output_file"
        return 0
      fi
      converted_file="${output_file%.*}.jpg"
      ;;
    pdf)
      if [[ "$ext" == "pdf" ]]; then
        printf '%s\n' "$output_file"
        return 0
      fi
      converted_file="${output_file%.*}.pdf"
      ;;
    *)
      printf '%s\n' "$output_file"
      return 0
      ;;
  esac

  if ! command -v convert >/dev/null 2>&1; then
    button_log "warn" "output conversion skipped for profile=${profile}: convert not found"
    return 1
  fi

  if [[ "$target_format" == "pdf" ]]; then
    if convert "${output_file}" -strip -compress jpeg -quality 90 "${converted_file}" >/tmp/scanservjs-brother-convert.log 2>&1 && [[ -s "${converted_file}" ]]; then
      button_log "info" "output conversion created ${converted_file} for profile=${profile}"
      rm -f "${output_file}"
      printf '%s\n' "${converted_file}"
      return 0
    fi
  else
    if convert "${output_file}" -strip -quality 92 "${converted_file}" >/tmp/scanservjs-brother-convert.log 2>&1 && [[ -s "${converted_file}" ]]; then
      button_log "info" "output conversion created ${converted_file} for profile=${profile}"
      rm -f "${output_file}"
      printf '%s\n' "${converted_file}"
      return 0
    fi
  fi

  button_log "warn" "output conversion failed for profile=${profile} file=${output_file}: $(cat /tmp/scanservjs-brother-convert.log 2>/dev/null || printf '<leer>')"
  rm -f "${converted_file}"
  return 1
}

prepare_paperless_copy_source() {
  local output_file="$1"
  local ext converted_file

  ext="${output_file##*.}"
  ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"
  case "$ext" in
    tif|tiff)
      ;;
    *)
      return 1
      ;;
  esac

  if ! command -v convert >/dev/null 2>&1; then
    button_log "warn" "paperless compatibility conversion skipped: convert not found"
    return 1
  fi

  converted_file="${output_file%.*}.jpg"
  if convert "${output_file}" -strip -quality 92 "${converted_file}" >/tmp/scanservjs-brother-convert.log 2>&1 && [[ -s "${converted_file}" ]]; then
    button_log "info" "paperless compatibility conversion created ${converted_file}"
    printf '%s\n' "${converted_file}"
    return 0
  fi

  button_log "warn" "paperless compatibility conversion failed for ${output_file}: $(cat /tmp/scanservjs-brother-convert.log 2>/dev/null || printf '<leer>')"
  rm -f "${converted_file}"
  return 1
}

copy_scan_output() {
  local output_file="$1"
  local profile="$2"
  local copy_file="${output_file}"
  local cleanup_copy_file="false"
  local converted_file=""

  if [[ -z "${COPY_SCANS_TO:-}" || "${COPY_SCANS_TO}" == "null" ]]; then
    return 0
  fi

  if ! copy_to_target_enabled_for_profile "$profile"; then
    button_log "info" "copy skipped for profile=${profile}: copy_to_target disabled"
    return 0
  fi

  if paperless_target_enabled; then
    if converted_file="$(prepare_paperless_copy_source "${output_file}")"; then
      copy_file="${converted_file}"
      cleanup_copy_file="true"
    fi
  fi

  mkdir -p "${COPY_SCANS_TO}" 2>/dev/null || true
  if ! cp -f "${copy_file}" "${COPY_SCANS_TO}/"; then
    button_log "error" "copy failed target=${COPY_SCANS_TO} file=${copy_file}"
    if [[ "${cleanup_copy_file}" == "true" ]]; then
      rm -f "${copy_file}"
    fi
    return 1
  fi

  button_log "info" "copied output to ${COPY_SCANS_TO}/$(basename "${copy_file}")"
  if [[ "${cleanup_copy_file}" == "true" ]]; then
    rm -f "${copy_file}"
  fi
}

detect_adf_source() {
  # Ermittelt den korrekten ADF-Source-Namen fuer den Scanner.
  # Brother brscan4 nutzt oft andere Namen als Standard-SANE.
  local device="$1"
  local options_output source_name

  options_output="$(scanimage -A -d "${device}" 2>/dev/null || true)"

  # Versuche verschiedene ADF-Bezeichnungen (haeufigste zuerst)
  for source_name in \
    "Automatic Document Feeder(left aligned)" \
    "Automatic Document Feeder" \
    "ADF" \
    "ADF Duplex" \
  ; do
    if grep -qF "${source_name}" <<<"${options_output}"; then
      printf '%s\n' "${source_name}"
      return 0
    fi
  done

  button_log "warn" "no ADF source found in scanimage options"
  return 1
}

scan_multipage() {
  # Multi-Page-Scan ueber ADF.
  # Gibt den Pfad zur fertigen Output-Datei auf stdout aus.
  #
  # ADF: scanimage --batch, scannt bis ADF leer (Exit-Code 7 = normal).
  # Fallback bei ADF-Fehler: Einzelseite vom Flachbett.
  local device="$1"
  local output_file="$2"
  local resolution="${BROTHER_BUTTON_DEFAULT_RESOLUTION:-300}"
  local tmpdir exit_code adf_source

  tmpdir="$(mktemp -d /tmp/brother_batch_XXXXXX)" || {
    button_log "error" "mktemp failed – cannot create temporary directory"
    return 1
  }

  # --- Versuche ADF ---
  adf_source=""
  if adf_source="$(detect_adf_source "${device}")"; then
    button_log "info" "ADF batch scan start device=${device} source='${adf_source}' resolution=${resolution}"

    exit_code=0
    scanimage \
      --device-name="${device}" \
      --source="${adf_source}" \
      --format=tiff \
      --resolution="${resolution}" \
      --batch="${tmpdir}/page_%04d.tif" 2>>"${BROTHER_BUTTON_LOG_FILE}" || exit_code=$?

    # Exit-Code 7 = "no more pages" (ADF leer) = OK
    if [[ "${exit_code}" -ne 0 && "${exit_code}" -ne 7 ]]; then
      button_log "warn" "ADF scan failed exit=${exit_code}, falling back to single flatbed page"
    else
      # ADF hat funktioniert — Seiten zaehlen
      local -a pages=()
      shopt -s nullglob
      pages=("${tmpdir}"/page_*.tif)
      shopt -u nullglob

      if [[ "${#pages[@]}" -gt 0 ]]; then
        _merge_pages "${tmpdir}" "${output_file}" "${#pages[@]}"
        return $?
      fi
      button_log "warn" "ADF produced 0 pages, falling back to single flatbed page"
    fi
  else
    button_log "info" "no ADF detected, falling back to single flatbed page"
  fi

  # --- Fallback: Einzelseite vom Flachbett ---
  # Rueckgabe "" signalisiert dem Aufrufer: kein Batch-Ergebnis,
  # soll normalen Single-Page-Pfad (mit skey-scanimage falls vorhanden) nutzen.
  button_log "info" "ADF unavailable, delegating to single-page scan path"
  rm -rf "${tmpdir}"
  return 2
}

_merge_pages() {
  # Fasst gescannte Seiten zu einer Datei zusammen.
  local tmpdir="$1"
  local output_file="$2"
  local page_count="$3"

  local -a pages=()
  shopt -s nullglob
  pages=("${tmpdir}"/page_*.tif)
  shopt -u nullglob

  page_count="${#pages[@]}"
  button_log "info" "merging ${page_count} pages"

  if [[ "${page_count}" -eq 0 ]]; then
    button_log "error" "no pages to merge"
    rm -rf "${tmpdir}"
    return 1
  fi

  if [[ "${page_count}" -eq 1 ]]; then
    mv "${pages[0]}" "${output_file%.*}.tif"
    rm -rf "${tmpdir}"
    printf '%s\n' "${output_file%.*}.tif"
    return 0
  fi

  # Mehrere Seiten — zu PDF zusammenfassen
  local pdf_output="${output_file%.*}.pdf"
  if command -v convert >/dev/null 2>&1; then
    if convert "${pages[@]}" -strip -compress jpeg -quality 90 "${pdf_output}" \
       >>"${BROTHER_BUTTON_LOG_FILE}" 2>&1 && [[ -s "${pdf_output}" ]]; then
      button_log "info" "merged ${page_count} pages into ${pdf_output}"
      rm -rf "${tmpdir}"
      printf '%s\n' "${pdf_output}"
      return 0
    fi
    button_log "warn" "convert merge failed, using first page only"
  else
    button_log "warn" "convert not found, using first page only"
  fi

  mv "${pages[0]}" "${output_file%.*}.tif"
  rm -rf "${tmpdir}"
  printf '%s\n' "${output_file%.*}.tif"
  return 0
}

scan_via_profile() {
  local profile="$1"
  local requested_device="${2:-}"
  local friendly_name="${3:-}"
  local device format ext output_dir output_file final_output_file converted_output_file
  local skey_bin=""
  local -a scan_args=()

  load_button_env

  output_dir="$(button_output_dir)"
  mkdir -p "${output_dir}"

  device="$(resolve_device "${requested_device}")"
  if [[ -z "${device}" ]]; then
    button_log "error" "no scanner device resolved for profile=${profile}"
    exit 1
  fi

  # --- Multi-Page Scan (ADF) ------------------------------------------------
  # Bei ADF-Modus: versuche ADF-Batch-Scan.
  # Return-Code 2 = ADF nicht verfuegbar → weiter zum normalen Single-Page-Pfad
  # Return-Code 1 = Scan-Fehler → Abbruch
  # Return-Code 0 = Erfolg → fertig
  if [[ "${BROTHER_SCAN_SOURCE:-FB}" == "ADF" ]]; then
    output_file="${output_dir}/button_${profile}_$(button_timestamp).tif"
    local batch_output batch_rc=0
    batch_output="$(scan_multipage "${device}" "${output_file}")" || batch_rc=$?

    if [[ "${batch_rc}" -eq 0 && -n "${batch_output}" ]]; then
      # ADF Batch hat funktioniert
      output_file="${batch_output}"

      if [[ ! -s "${output_file}" ]]; then
        rm -f "${output_file}"
        button_log "error" "empty output file profile=${profile} output=${output_file}"
        exit 1
      fi

      final_output_file="${output_file}"
      if [[ "${output_file}" != *.pdf ]]; then
        if converted_output_file="$(convert_profile_output "${profile}" "${output_file}")"; then
          final_output_file="${converted_output_file}"
        fi
      fi

      copy_scan_output "${final_output_file}" "${profile}"
      button_log "info" "scan saved profile=${profile} output=${final_output_file} size=$(wc -c <"${final_output_file}" 2>/dev/null || printf '0')"
      BROTHER_LAST_OUTPUT_FILE="${final_output_file}"
      export BROTHER_LAST_OUTPUT_FILE
      return 0
    elif [[ "${batch_rc}" -eq 2 ]]; then
      # ADF nicht verfuegbar → weiter zum Single-Page-Pfad (skey-scanimage)
      # WICHTIG: Source auf Flachbett setzen, damit skey-scanimage/scanimage nicht
      # versucht, vom ADF zu scannen (der ja nicht verfuegbar ist)
      BROTHER_SCAN_SOURCE="FB"
      button_log "info" "ADF fallback: using standard single-page scan for profile=${profile} (source forced to FB)"
    else
      button_log "error" "multipage scan failed for profile=${profile}"
      exit 1
    fi
  fi

  # --- Single-Page Scan (Flachbett) ----------------------------------------
  if [[ -x "/opt/brother/scanner/brscan-skey/skey-scanimage" ]]; then
    skey_bin="/opt/brother/scanner/brscan-skey/skey-scanimage"
    format="tiff"
    ext="tif"
    output_file="${output_dir}/button_${profile}_$(button_timestamp).${ext}"
    scan_args=(--device-name "${device}" --outputfile "${output_file}")
    append_skey_args "${profile}" scan_args
    button_log "info" "scan start profile=${profile} mode=skey device=${device} output=${output_file}"
    if "${skey_bin}" "${scan_args[@]}"; then
      :
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

    button_log "info" "scan start profile=${profile} mode=generic device=${device} output=${output_file}"
    if scanimage "${scan_args[@]}" >"${output_file}"; then
      :
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

  final_output_file="${output_file}"
  if converted_output_file="$(convert_profile_output "${profile}" "${output_file}")"; then
    final_output_file="${converted_output_file}"
  fi

  copy_scan_output "${final_output_file}" "${profile}"
  button_log "info" "scan saved profile=${profile} output=${final_output_file} size=$(wc -c <"${final_output_file}" 2>/dev/null || printf '0')"
  BROTHER_LAST_OUTPUT_FILE="${final_output_file}"
  export BROTHER_LAST_OUTPUT_FILE
}

trigger_webhook() {
  local button="$1"
  local webhook_var="$2"
  local requested_device="${3:-}"
  local friendly_name="${4:-}"
  local output_file="${5:-}"
  local output_basename=""
  local webhook_id device payload timestamp

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
  if [[ -n "${output_file}" ]]; then
    output_basename="$(basename "${output_file}")"
  fi
  timestamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  payload="$(jq -nc \
    --arg source 'scanservjs_brother_frontpanel' \
    --arg button "${button}" \
    --arg device "${device}" \
    --arg scanner_name "${BROTHER_SCANNER_NAME:-}" \
    --arg friendly_name "${friendly_name}" \
    --arg output_file "${output_file}" \
    --arg output_basename "${output_basename}" \
    --arg copy_scans_to "${COPY_SCANS_TO:-}" \
    --arg timestamp "${timestamp}" \
    '{source:$source,button:$button,device:$device,scanner_name:$scanner_name,friendly_name:$friendly_name,output_file:$output_file,output_basename:$output_basename,copy_scans_to:$copy_scans_to,timestamp:$timestamp}')"

  curl -fsS \
    -X POST \
    -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    "http://supervisor/core/api/webhook/${webhook_id}" >/dev/null
  button_log "info" "webhook delivered button=${button} webhook_id=${webhook_id}"
}
