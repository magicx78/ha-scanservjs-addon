#!/usr/bin/env bashio
set -euo pipefail

CONFIG_PATH="/data/options.json"
DELIMITER="${DELIMITER:-;}"
APP_DIR="${APP_DIR:-}"
RUNTIME_REVISION="2026-03-17-r31"
AI_SCRIPTS_DIR="/opt/paperless-ai"
AI_CONFIG_FILE="${AI_SCRIPTS_DIR}/config.yaml"

log() {
  bashio::log.info "$*"
}

warn() {
  bashio::log.warning "$*"
}

err() {
  bashio::log.error "$*"
}

log_cmd_output() {
  local label="$1"
  shift
  local output

  if output="$("$@" 2>&1)"; then
    log "${label}: ${output:-<leer>}"
  else
    warn "${label} fehlgeschlagen: ${output:-<leer>}"
  fi
}

run_with_timeout() {
  local seconds="$1"
  shift

  if command -v timeout >/dev/null 2>&1; then
    timeout --foreground "${seconds}" "$@"
  else
    "$@"
  fi
}

log_cmd_output_timeout() {
  local label="$1"
  local seconds="$2"
  shift 2
  local output=""
  local status=0

  if output="$(run_with_timeout "$seconds" "$@" 2>&1)"; then
    log "${label}: ${output:-<leer>}"
    return 0
  fi

  status=$?
  if [[ "$status" -eq 124 ]]; then
    warn "${label} Timeout nach ${seconds}s: ${output:-<leer>}"
  else
    warn "${label} fehlgeschlagen: ${output:-<leer>}"
  fi
}

opt() {
  local query="$1"
  jq -r "${query}" "${CONFIG_PATH}"
}

route_interface_for_ip() {
  local ip="$1"
  ip route get "$ip" 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}'
}

route_source_for_ip() {
  local ip="$1"
  ip route get "$ip" 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i=="src") {print $(i+1); exit}}'
}

normalize_brother_model() {
  local model="$1"
  case "$model" in
    MFC-L2710DW|MFC-L2710DN|MFC-L2712DN)
      printf "MFC-L2700DW\n"
      ;;
    *)
      printf "%s\n" "$model"
      ;;
  esac
}

detect_app_dir() {
  local candidate

  if [[ -n "${APP_DIR}" && -f "${APP_DIR}/server/server.js" ]]; then
    printf "%s\n" "${APP_DIR}"
    return 0
  fi

  for candidate in /usr/lib/scanservjs /app; do
    if [[ -f "${candidate}/server/server.js" ]]; then
      printf "%s\n" "${candidate}"
      return 0
    fi
  done

  return 1
}

ensure_airscan_config() {
  local file="/etc/sane.d/airscan.conf"
  touch "$file"
  grep -Fqx "[devices]" "$file" || printf "[devices]\n" >> "$file"
}

ensure_generic_airscan_fallbacks() {
  local ip="$1"

  [[ -n "$ip" && "$ip" != "null" ]] || return 0

  ensure_airscan_config
  ensure_line "Generic eSCL = http://${ip}/eSCL, eSCL" "/etc/sane.d/airscan.conf"
  ensure_line "Generic WSD = http://${ip}/WebServices/ScannerService, WSD" "/etc/sane.d/airscan.conf"
}

ensure_snmp_runtime_dirs() {
  local cert_dir="/var/lib/snmp/cert_indexes"
  mkdir -p "${cert_dir}" 2>/dev/null || true
}

resolve_copy_scans_to() {
  local mode="$1"
  local custom_path="$2"
  local paperless_path="/share/paperless/consume"

  case "$mode" in
    auto|"")
      if [[ -d "$paperless_path" ]]; then
        printf "%s\n" "$paperless_path"
      else
        printf "%s\n" "$custom_path"
      fi
      ;;
    paperless)
      printf "%s\n" "$paperless_path"
      ;;
    custom)
      printf "%s\n" "$custom_path"
      ;;
    *)
      warn "Unbekannter copy_scans_to_mode=${mode}; verwende custom."
      printf "%s\n" "$custom_path"
      ;;
  esac
}

split_delim_lines() {
  printf "%s" "$1" | tr "${DELIMITER}" '\n' | sed '/^[[:space:]]*$/d'
}

join_delim_lines() {
  local first="true"
  local line

  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    if [[ "$first" == "true" ]]; then
      printf "%s" "$line"
      first="false"
    else
      printf "%s%s" "${DELIMITER}" "$line"
    fi
  done
}

ensure_line() {
  local line="$1"
  local file="$2"

  touch "$file"
  grep -Fxq "$line" "$file" || echo "$line" >> "$file"
}

pad_ip() {
  local ip="$1"
  local a b c d
  IFS='.' read -r a b c d <<<"$ip"
  printf "%03d.%03d.%03d.%03d" "$a" "$b" "$c" "$d"
}

brsane_supports_q() {
  command -v brsaneconfig4 >/dev/null 2>&1 || return 1
  brsaneconfig4 --help 2>/dev/null | grep -q -- ' -q'
}

brother_cfg_file() {
  echo "/etc/opt/brother/scanner/brscan4/brsanenetdevice4.cfg"
}

brother_button_template_dir() {
  echo "/opt/scanservjs-brother-skey"
}

brother_button_target_dir() {
  echo "/opt/brother/scanner/brscan-skey/script"
}

first_delim_item() {
  printf "%s" "$1" | tr "${DELIMITER}" '\n' | sed -n '/^[[:space:]]*$/d;1p'
}

first_device_item() {
  local value="$1"
  local match=""

  match="$(printf "%s\n" "$value" | grep -Eo 'brother[0-9]+:net[0-9]+;dev[0-9]+' | head -n 1 || true)"
  if [[ -n "$match" ]]; then
    printf "%s\n" "$match"
    return 0
  fi

  first_delim_item "$value"
}

write_shell_var() {
  local name="$1"
  local value="$2"

  printf '%s=%q\n' "$name" "$value"
}

warmup_brother_device() {
  local device="$1"
  local attempts=0

  [[ -n "$device" && "$device" != "null" ]] || return 0
  command -v scanimage >/dev/null 2>&1 || return 0

  while (( attempts < 2 )); do
    if run_with_timeout 12 scanimage -A -d "$device" >/tmp/brother-device-warmup.log 2>&1; then
      log "Brother Device-Warmup erfolgreich: ${device}"
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 1
  done

  warn "Brother Device-Warmup fehlgeschlagen: $(cat /tmp/brother-device-warmup.log 2>/dev/null || printf '<leer>')"
  return 0
}

configure_scanimage_discovery() {
  local ignore="$1"

  if [[ "$ignore" == "true" ]]; then
    export SCANIMAGE_LIST_IGNORE="true"
    log "scanservjs Discovery: scanimage -L deaktiviert"
  else
    unset SCANIMAGE_LIST_IGNORE
    log "scanservjs Discovery: scanimage -L aktiviert"
  fi
}

discover_brother_device_ids() {
  {
    command -v brscan-skey >/dev/null 2>&1 && run_with_timeout 5 brscan-skey -l 2>/dev/null || true
    command -v brsaneconfig4 >/dev/null 2>&1 && run_with_timeout 5 brsaneconfig4 -q 2>/dev/null || true
  } | grep -Eo 'brother[0-9]+:net[0-9]+;dev[0-9]+' | awk '!seen[$0]++' || true
}

probe_brother_device_ids() {
  local net_idx dev_idx candidate
  local output

  command -v scanimage >/dev/null 2>&1 || return 0

  for net_idx in 1 2 3 4; do
    for dev_idx in 0 1; do
      candidate="brother4:net${net_idx};dev${dev_idx}"
      if output="$(run_with_timeout 8 scanimage -A -d "$candidate" 2>&1)" && grep -Fq "All options specific to device" <<<"$output"; then
        printf "%s\n" "$candidate"
      fi
    done
  done | awk '!seen[$0]++'
}

ensure_brother_sane_links() {
  local src_dirs=("/usr/lib64/sane" "/opt/brother/scanner/brscan4")
  local dst_dirs=("/usr/lib/x86_64-linux-gnu/sane" "/usr/lib64/sane")
  local src_dir dst_dir
  local target
  local linked="false"

  for src_dir in "${src_dirs[@]}"; do
    [[ -d "$src_dir" ]] || continue
    for dst_dir in "${dst_dirs[@]}"; do
      [[ -d "$dst_dir" ]] || continue
      shopt -s nullglob
      for lib in "$src_dir"/libsane-brother*.so*; do
        target="$dst_dir/$(basename "$lib")"
        if [[ "$lib" == "$target" ]] || [[ -e "$target" && "$lib" -ef "$target" ]]; then
          continue
        fi
        ln -sf "$lib" "$target"
        linked="true"
      done
      shopt -u nullglob
    done
  done

  if [[ "$linked" == "true" ]]; then
    log "Brother libsane Links aktualisiert"
  fi
}

setup_brother_library_paths() {
  local base="${LD_LIBRARY_PATH:-}"
  local extras="/opt/brother/scanner/brscan4:/usr/lib64:/usr/lib64/sane:/usr/lib/x86_64-linux-gnu/sane"

  if [[ -n "$base" ]]; then
    export LD_LIBRARY_PATH="${extras}:${base}"
  else
    export LD_LIBRARY_PATH="${extras}"
  fi
  log "LD_LIBRARY_PATH fuer Brother gesetzt"
}

install_brother_button_scripts() {
  local src_dir dst_dir file

  src_dir="$(brother_button_template_dir)"
  dst_dir="$(brother_button_target_dir)"

  if [[ ! -d "$src_dir" ]]; then
    warn "Brother Button-Skriptquelle fehlt: ${src_dir}"
    return 0
  fi

  mkdir -p "$dst_dir"
  shopt -s nullglob
  for file in "$src_dir"/*.sh; do
    install -m 0755 "$file" "${dst_dir}/$(basename "$file")"
  done
  shopt -u nullglob

  log "Brother Button-Skripte installiert: ${dst_dir}"
}

write_brother_button_env() {
  local scanner_name="$1"
  local env_file default_device output_dir app_dir_detected

  env_file="$(brother_button_target_dir)/scanservjs.env"
  mkdir -p "$(dirname "$env_file")"

  default_device="$(first_device_item "${DEVICES:-}")"
  if [[ -z "$default_device" ]]; then
    default_device="$(discover_brother_device_ids | head -n 1 || true)"
  fi
  if [[ -z "$default_device" ]]; then
    default_device="$(probe_brother_device_ids | head -n 1 || true)"
  fi

  output_dir="/data/output"
  if app_dir_detected="$(detect_app_dir 2>/dev/null)"; then
    output_dir="${app_dir_detected}/data/output"
  fi
  if [[ -n "${BROTHER_BUTTON_OUTPUT_DIR_OVERRIDE:-}" && "${BROTHER_BUTTON_OUTPUT_DIR_OVERRIDE}" != "null" ]]; then
    output_dir="${BROTHER_BUTTON_OUTPUT_DIR_OVERRIDE}"
  fi

  {
    write_shell_var "COPY_SCANS_TO" "${COPY_SCANS_TO:-}"
    write_shell_var "BROTHER_BUTTON_OUTPUT_DIR" "${output_dir}"
    write_shell_var "BROTHER_BUTTON_DEFAULT_RESOLUTION" "${BROTHER_BUTTON_DEFAULT_RESOLUTION:-300}"
    write_shell_var "BROTHER_BUTTON_SCAN_FORMAT" "${BROTHER_BUTTON_SCAN_FORMAT:-jpeg}"
    write_shell_var "BROTHER_IMAGE_OUTPUT_FORMAT" "${BROTHER_IMAGE_OUTPUT_FORMAT:-jpg}"
    write_shell_var "BROTHER_OCR_OUTPUT_FORMAT" "${BROTHER_OCR_OUTPUT_FORMAT:-pdf}"
    write_shell_var "BROTHER_COPY_FILE_TO_TARGET" "${BROTHER_COPY_FILE_TO_TARGET:-true}"
    write_shell_var "BROTHER_COPY_EMAIL_TO_TARGET" "${BROTHER_COPY_EMAIL_TO_TARGET:-true}"
    write_shell_var "BROTHER_COPY_IMAGE_TO_TARGET" "${BROTHER_COPY_IMAGE_TO_TARGET:-false}"
    write_shell_var "BROTHER_COPY_OCR_TO_TARGET" "${BROTHER_COPY_OCR_TO_TARGET:-false}"
    write_shell_var "BROTHER_BUTTON_SCAN_ARGS_FILE" "${BROTHER_BUTTON_SCAN_ARGS_FILE:-}"
    write_shell_var "BROTHER_BUTTON_SCAN_ARGS_EMAIL" "${BROTHER_BUTTON_SCAN_ARGS_EMAIL:-}"
    write_shell_var "BROTHER_TRIGGER_IMAGE_WEBHOOK_ID" "${BROTHER_TRIGGER_IMAGE_WEBHOOK_ID:-}"
    write_shell_var "BROTHER_TRIGGER_OCR_WEBHOOK_ID" "${BROTHER_TRIGGER_OCR_WEBHOOK_ID:-}"
    write_shell_var "BROTHER_DEFAULT_DEVICE" "${default_device}"
    write_shell_var "BROTHER_SCANNER_NAME" "${scanner_name}"
    write_shell_var "SUPERVISOR_TOKEN" "${SUPERVISOR_TOKEN:-}"
  } > "$env_file"

  chmod 600 "$env_file"
  mkdir -p "${output_dir}" 2>/dev/null || true
  BROTHER_DEFAULT_DEVICE_RESOLVED="${default_device}"
  export BROTHER_DEFAULT_DEVICE_RESOLVED
  log "Brother Button-Umgebung geschrieben: ${env_file} (output=${output_dir})"
}

brother_is_registered() {
  local name="$1"
  local model="$2"
  local ip="$3"
  local nodename="$4"
  local cfg

  if brsane_supports_q; then
    local qout
    qout="$(brsaneconfig4 -q 2>/dev/null || true)"
    if [[ -n "$ip" && "$ip" != "null" ]] && echo "$qout" | grep -Fq "$name" && echo "$qout" | grep -Fq "$ip"; then
      return 0
    fi
    if [[ -n "$nodename" && "$nodename" != "null" ]] && echo "$qout" | grep -Fq "$name" && echo "$qout" | grep -Fq "$nodename"; then
      return 0
    fi
  fi

  cfg="$(brother_cfg_file)"
  [[ -f "$cfg" ]] || return 1

  if [[ -n "$ip" && "$ip" != "null" ]]; then
    local ip_padded
    ip_padded="$(pad_ip "$ip")"
    if grep -Eq "DEVICE=${name}[[:space:]]*," "$cfg" \
      && grep -Eq "IP-ADDRESS=${ip_padded}$" "$cfg" \
      && { [[ -z "$model" || "$model" == "null" ]] || grep -Fq "\"${model}\"" "$cfg"; }; then
      return 0
    fi
  fi

  if [[ -n "$nodename" && "$nodename" != "null" ]] && grep -Fq "$nodename" "$cfg" && grep -Eq "DEVICE=${name}[[:space:]]*," "$cfg"; then
    return 0
  fi

  return 1
}

resolve_brother_registered_ip() {
  local name="$1"
  local qout line

  command -v brsaneconfig4 >/dev/null 2>&1 || return 1
  qout="$(brsaneconfig4 -q 2>/dev/null || true)"

  while IFS= read -r line; do
    [[ -n "$name" && "$line" == *"$name"* ]] || continue
    if [[ "$line" =~ \[[[:space:]]*([0-9.]+)\] ]]; then
      printf "%s\n" "${BASH_REMATCH[1]}"
      return 0
    fi
  done <<<"$qout"

  return 1
}

install_brscan4() {
  local accept="$1"
  local source="$2"
  local url="$3"
  local sha="$4"
  local local_path="$5"
  local deb="/tmp/brscan4.amd64.deb"
  local skey_deb="/tmp/brscan-skey.amd64.deb"
  local skey_url_legacy="https://download.brother.com/welcome/dlf006652/brscan-skey-0.3.2-0.amd64.deb"
  local skey_url_current="https://download.brother.com/pub/com/linux/linux/packages/brscan-skey-0.3.2-0.amd64.deb"
  local has_brscan4="false"
  local has_skey="false"

  if dpkg -s brscan4 >/dev/null 2>&1 || command -v brsaneconfig4 >/dev/null 2>&1; then
    has_brscan4="true"
  fi
  if dpkg -s brscan-skey >/dev/null 2>&1 || command -v brscan-skey >/dev/null 2>&1; then
    has_skey="true"
  fi

  if [[ "$accept" != "true" ]]; then
    warn "brother_enable=true, aber brother_accept_eula=false - Treiberinstallation uebersprungen."
    return 0
  fi

  if [[ "$has_brscan4" == "true" && "$has_skey" == "true" ]]; then
    log "brscan4 und brscan-skey scheinen bereits installiert - skip."
    ensure_line "brother4" "/etc/sane.d/dll.conf"
    return 0
  fi

  if [[ "$(id -u)" != "0" ]]; then
    err "brscan4 Installation erfordert root im Container."
    return 1
  fi

  log "Installiere brscan4 - Quelle: ${source}"
  apt-get update
  apt-get install -y --no-install-recommends curl ca-certificates

  if [[ "$has_brscan4" != "true" ]]; then
    if [[ "$source" == "local" ]]; then
      if [[ -z "$local_path" || "$local_path" == "null" || ! -f "$local_path" ]]; then
        err "Lokale .deb Datei fehlt: ${local_path}"
        return 1
      fi
      cp -f "$local_path" "$deb"
    elif [[ "$source" == "url" ]]; then
      if [[ -z "$url" || "$url" == "null" ]]; then
        err "brother_driver_source=url, aber brother_driver_url ist leer."
        return 1
      fi
      curl -fL --retry 3 --retry-delay 2 -o "$deb" "$url"
    else
      local lnk debname
      lnk="$(curl -fsSL "https://download.brother.com/pub/com/linux/linux/infs/brscan4.lnk")"
      debname="$(printf "%s" "$lnk" | tr ' ' '\n' | grep '^DEB64=' | cut -d= -f2)"
      if [[ -z "$debname" ]]; then
        err "Konnte DEB64 aus brscan4.lnk nicht parsen."
        return 1
      fi
      curl -fL --retry 3 --retry-delay 2 -o "$deb" "https://download.brother.com/pub/com/linux/linux/packages/${debname}"
    fi

    if [[ -n "$sha" && "$sha" != "null" ]]; then
      log "Pruefe SHA256 fuer brscan4 Paket"
      echo "${sha}  ${deb}" | sha256sum -c -
    fi

    dpkg -i "$deb" || true
  else
    log "brscan4 bereits vorhanden - nur brscan-skey Pruefung."
  fi

  if [[ "$has_skey" != "true" ]]; then
    if ! curl -fL --retry 3 --retry-delay 2 -o "$skey_deb" "$skey_url_current"; then
      warn "Aktuelle brscan-skey URL fehlgeschlagen, versuche Legacy URL"
      curl -fL --retry 3 --retry-delay 2 -o "$skey_deb" "$skey_url_legacy"
    fi
    dpkg -i "$skey_deb" || true
  fi

  apt-get -y -f install
  apt-get clean
  rm -rf /var/lib/apt/lists/*
  rm -f "$deb"
  rm -f "$skey_deb"
  ensure_line "brother4" "/etc/sane.d/dll.conf"
  ensure_brother_sane_links
}

configure_brscan_skey() {
  local target_ip="$1"
  local config="/opt/brother/scanner/brscan-skey/brscan-skey.config"
  local iface source_ip

  command -v brscan-skey >/dev/null 2>&1 || return 0
  [[ -f "$config" ]] || {
    warn "brscan-skey Konfiguration nicht gefunden: ${config}"
    return 0
  }

  iface="$(route_interface_for_ip "$target_ip")"
  source_ip="$(route_source_for_ip "$target_ip")"

  if [[ -z "$iface" ]]; then
    warn "Konnte Netzwerk-Interface fuer ${target_ip} nicht ermitteln."
  fi
  if [[ -z "$source_ip" ]]; then
    warn "Konnte Quell-IP fuer ${target_ip} nicht ermitteln."
  fi

  sed -i '/^eth=/d;/^ip_address=/d' "$config"
  [[ -n "$iface" ]] && printf "eth=%s\n" "$iface" >> "$config"
  [[ -n "$source_ip" ]] && printf "ip_address=%s\n" "$source_ip" >> "$config"

  log "brscan-skey config: eth=${iface:-<leer>} ip_address=${source_ip:-<leer>}"
}

start_brscan_skey() {
  local skey_bin=""
  local skey_proc="brscan-skey-exe"
  if command -v brscan-skey >/dev/null 2>&1; then
    skey_bin="$(command -v brscan-skey)"
  elif [[ -x /opt/brother/scanner/brscan-skey/brscan-skey ]]; then
    skey_bin="/opt/brother/scanner/brscan-skey/brscan-skey"
  else
    warn "brscan-skey Binary nicht gefunden."
    return 0
  fi

  if pgrep -x "$skey_proc" >/dev/null 2>&1 || pgrep -x brscan-skey >/dev/null 2>&1; then
    log "brscan-skey laeuft bereits"
    return 0
  fi

  "${skey_bin}" >/tmp/brscan-skey.log 2>&1 &
  sleep 1

  if pgrep -x "$skey_proc" >/dev/null 2>&1 || pgrep -x brscan-skey >/dev/null 2>&1; then
    log "brscan-skey gestartet"
  else
    log "brscan-skey Prozesspruefung uneindeutig; Frontpanel-Funktion kann trotzdem verfuegbar sein"
    if [[ -s /tmp/brscan-skey.log ]]; then
      log "brscan-skey log: $(tail -n 20 /tmp/brscan-skey.log)"
    fi
  fi

  return 0
}

register_brother() {
  local do_reg="$1"
  local name="$2"
  local model="$3"
  local ip="$4"
  local nodename="$5"
  local overwrite="$6"
  local effective_model

  [[ "$do_reg" == "true" ]] || {
    log "Brother Registrierung deaktiviert"
    return 0
  }

  if ! command -v brsaneconfig4 >/dev/null 2>&1; then
    warn "brsaneconfig4 fehlt - Registrierung nicht moeglich."
    return 0
  fi

  if [[ -z "$name" || "$name" == "null" || -z "$model" || "$model" == "null" ]]; then
    err "brother_scanner_name und brother_scanner_model muessen gesetzt sein."
    return 1
  fi

  if [[ -z "$nodename" || "$nodename" == "null" ]] && [[ -z "$ip" || "$ip" == "null" ]]; then
    warn "brother_scanner_ip fehlt. Alternativ brother_scanner_nodename setzen. Brother-Registrierung wird uebersprungen."
    return 0
  fi

  effective_model="$(normalize_brother_model "$model")"
  if [[ "$effective_model" != "$model" ]]; then
    warn "Brother Modell-Mapping aktiv: ${model} -> ${effective_model}"
  fi

  if [[ "$overwrite" == "true" ]]; then
    log "overwrite=true - versuche vorhandenen Eintrag ${name} zu entfernen"
    brsaneconfig4 -r "$name" || true
  elif brother_is_registered "$name" "$effective_model" "$ip" "$nodename"; then
    log "Brother Scanner ${name} ist bereits registriert - skip."
    return 0
  fi

  if [[ -n "$nodename" && "$nodename" != "null" ]]; then
    log "Registriere Brother Scanner per nodename=${nodename}"
    brsaneconfig4 -a "name=${name}" "model=${effective_model}" "nodename=${nodename}"
  else
    log "Registriere Brother Scanner per ip=${ip}"
    brsaneconfig4 -a "name=${name}" "model=${effective_model}" "ip=${ip}"
  fi
}

# ---------------------------------------------------------------------------
# KI-Konfiguration aus HA-Addon-Optionen generieren
# ---------------------------------------------------------------------------

write_ai_config() {
  local api_key paperless_url paperless_token ha_notify min_konfidenz log_level

  api_key="$(opt '.anthropic_api_key // ""')"
  paperless_url="$(opt '.paperless_url // "http://ca5234a0-paperless-ngx:8000"')"
  paperless_token="$(opt '.paperless_token // ""')"
  ha_notify="$(opt '.ha_notify_target // "notify.persistent_notification"')"
  min_konfidenz="$(opt '.min_konfidenz // 0.7')"
  log_level="INFO"

  if [[ -z "$api_key" || "$api_key" == "null" || "$api_key" == '""' ]]; then
    warn "anthropic_api_key nicht gesetzt – KI-Klassifikation deaktiviert."
    return 1
  fi
  if [[ -z "$paperless_token" || "$paperless_token" == "null" || "$paperless_token" == '""' ]]; then
    warn "paperless_token nicht gesetzt – KI-Klassifikation deaktiviert."
    return 1
  fi

  # HA-Token und URL aus Supervisor-Umgebung
  local ha_url="http://supervisor/core"
  local ha_token="${SUPERVISOR_TOKEN:-}"

  cat > "${AI_CONFIG_FILE}" <<YAML
# Automatisch generiert vom Addon – nicht manuell bearbeiten
paperless_url:    "${paperless_url}"
paperless_token:  "${paperless_token}"
anthropic_api_key: "${api_key}"
ha_url:           "${ha_url}"
ha_token:         "${ha_token}"
ha_notify_target: "${ha_notify}"
min_konfidenz:    ${min_konfidenz}
log_level:        "${log_level}"
YAML

  chmod 600 "${AI_CONFIG_FILE}"
  log "KI-Konfiguration geschrieben: ${AI_CONFIG_FILE}"
  return 0
}

start_ai_cron() {
  local interval
  interval="$(opt '.ai_poll_interval // 5')"

  # Cron-Datei schreiben
  echo "*/${interval} * * * * root /opt/venv/bin/python3 ${AI_SCRIPTS_DIR}/poll_new_docs.py >> /data/paperless-ai.log 2>&1" \
    > /etc/cron.d/paperless-ai
  chmod 644 /etc/cron.d/paperless-ai

  # Cron starten
  cron
  log "Paperless-AI Cron gestartet (alle ${interval} Minuten)"
}

main() {
  export SANED_NET_HOSTS AIRSCAN_DEVICES SCANIMAGE_LIST_IGNORE DEVICES OCR_LANG COPY_SCANS_TO
  export BROTHER_BUTTON_OUTPUT_DIR_OVERRIDE
  export BROTHER_BUTTON_DEFAULT_RESOLUTION BROTHER_BUTTON_SCAN_FORMAT BROTHER_BUTTON_SCAN_ARGS_FILE BROTHER_BUTTON_SCAN_ARGS_EMAIL
  export BROTHER_IMAGE_OUTPUT_FORMAT BROTHER_OCR_OUTPUT_FORMAT
  export BROTHER_COPY_FILE_TO_TARGET BROTHER_COPY_EMAIL_TO_TARGET BROTHER_COPY_IMAGE_TO_TARGET BROTHER_COPY_OCR_TO_TARGET
  export BROTHER_TRIGGER_IMAGE_WEBHOOK_ID BROTHER_TRIGGER_OCR_WEBHOOK_ID

  if [[ ! -f "${CONFIG_PATH}" ]]; then
    err "Addon-Konfiguration fehlt: ${CONFIG_PATH}"
    return 1
  fi

  log "Runtime-Revision: ${RUNTIME_REVISION}"

  SANED_NET_HOSTS="$(opt '.saned_net_hosts // ""')"
  AIRSCAN_DEVICES="$(opt '.airscan_devices // ""')"
  SCANIMAGE_LIST_IGNORE="$(opt '.scanimage_list_ignore // false')"
  DEVICES="$(opt '.devices // ""')"
  OCR_LANG="$(opt '.ocr_lang // "eng"')"
  local copy_scans_to_mode copy_scans_to_custom
  copy_scans_to_mode="$(opt '.copy_scans_to_mode // "custom"')"
  copy_scans_to_custom="$(opt '.copy_scans_to // ""')"
  COPY_SCANS_TO="$(resolve_copy_scans_to "$copy_scans_to_mode" "$copy_scans_to_custom")"
  local generic_scanner_ip
  generic_scanner_ip="$(opt '.generic_scanner_ip // ""')"
  BROTHER_BUTTON_OUTPUT_DIR_OVERRIDE="$(opt '.brother_button_output_dir // ""')"
  BROTHER_BUTTON_DEFAULT_RESOLUTION="$(opt '.brother_button_default_resolution // 300')"
  BROTHER_BUTTON_SCAN_FORMAT="$(opt '.brother_button_scan_format // "jpeg"')"
  BROTHER_IMAGE_OUTPUT_FORMAT="$(opt '.brother_image_output_format // "jpg"')"
  BROTHER_OCR_OUTPUT_FORMAT="$(opt '.brother_ocr_output_format // "pdf"')"
  BROTHER_COPY_FILE_TO_TARGET="$(opt '.brother_copy_file_to_target // true')"
  BROTHER_COPY_EMAIL_TO_TARGET="$(opt '.brother_copy_email_to_target // true')"
  BROTHER_COPY_IMAGE_TO_TARGET="$(opt '.brother_copy_image_to_target // false')"
  BROTHER_COPY_OCR_TO_TARGET="$(opt '.brother_copy_ocr_to_target // false')"
  BROTHER_BUTTON_SCAN_ARGS_FILE="$(opt '.brother_button_scan_args_file // ""')"
  BROTHER_BUTTON_SCAN_ARGS_EMAIL="$(opt '.brother_button_scan_args_email // ""')"
  BROTHER_TRIGGER_IMAGE_WEBHOOK_ID="$(opt '.brother_trigger_image_webhook_id // ""')"
  BROTHER_TRIGGER_OCR_WEBHOOK_ID="$(opt '.brother_trigger_ocr_webhook_id // ""')"
  local fallback_scanner_ip
  fallback_scanner_ip="${generic_scanner_ip}"
  if [[ -z "$fallback_scanner_ip" || "$fallback_scanner_ip" == "null" ]]; then
    fallback_scanner_ip="$(opt '.brother_scanner_ip // ""')"
  fi

  configure_scanimage_discovery "$SCANIMAGE_LIST_IGNORE"

  ensure_line "airscan" "/etc/sane.d/dll.conf"

  if [[ "$copy_scans_to_mode" == "auto" ]]; then
    if [[ "$COPY_SCANS_TO" == "/share/paperless/consume" && -d "/share/paperless/consume" ]]; then
      log "COPY_SCANS_TO auto: Paperless-Verzeichnis erkannt (${COPY_SCANS_TO})"
    else
      log "COPY_SCANS_TO auto: kein Paperless-Verzeichnis erkannt, verwende Wunschpfad (${COPY_SCANS_TO:-<leer>})"
    fi
  else
    log "COPY_SCANS_TO mode=${copy_scans_to_mode} pfad=${COPY_SCANS_TO:-<leer>}"
  fi

  if [[ -n "$COPY_SCANS_TO" && "$COPY_SCANS_TO" != "null" ]]; then
    mkdir -p "$COPY_SCANS_TO" || true
  fi

  if [[ -n "$SANED_NET_HOSTS" && "$SANED_NET_HOSTS" != "null" ]]; then
    while IFS= read -r host; do
      ensure_line "$host" "/etc/sane.d/net.conf"
    done < <(split_delim_lines "$SANED_NET_HOSTS")
  fi

  if [[ -n "$AIRSCAN_DEVICES" && "$AIRSCAN_DEVICES" != "null" ]]; then
    ensure_airscan_config
    while IFS= read -r devline; do
      grep -Fqx "$devline" /etc/sane.d/airscan.conf 2>/dev/null || sed -i "/^\[devices\]/a $devline" /etc/sane.d/airscan.conf
    done < <(split_delim_lines "$AIRSCAN_DEVICES")
  else
    if [[ -n "$fallback_scanner_ip" && "$fallback_scanner_ip" != "null" ]]; then
      log "AirScan Fallback aktiv fuer Scanner-IP: ${fallback_scanner_ip}"
    fi
    ensure_generic_airscan_fallbacks "$fallback_scanner_ip"
  fi

  local benable
  benable="$(opt '.brother_enable // false')"
  if [[ "${ENABLE_BROTHER_SUPPORT}" != "true" ]]; then
    benable="false"
    log "Brother Support per ENABLE_BROTHER_SUPPORT=false deaktiviert"
  fi
  if [[ "$benable" == "true" ]]; then
    local baccept bsrc burl bsha blocal doreg bname bmodel bip bnode bow recovered_ip
    log "Brother Support aktiviert"
    baccept="$(opt '.brother_accept_eula // false')"
    bsrc="$(opt '.brother_driver_source // "auto"')"
    burl="$(opt '.brother_driver_url // ""')"
    bsha="$(opt '.brother_driver_sha256 // ""')"
    blocal="$(opt '.brother_driver_local_path // ""')"
    doreg="$(opt '.brother_register_scanner // true')"
    bname="$(opt '.brother_scanner_name // "Brother"')"
    bmodel="$(opt '.brother_scanner_model // "MFC-L2700DW"')"
    bip="$(opt '.brother_scanner_ip // ""')"
    bnode="$(opt '.brother_scanner_nodename // ""')"
    bow="$(opt '.brother_overwrite_existing // false')"

    if [[ -z "$bip" || "$bip" == "null" ]] && [[ -z "$bnode" || "$bnode" == "null" ]]; then
      recovered_ip="$(resolve_brother_registered_ip "$bname" || true)"
      if [[ -n "$recovered_ip" ]]; then
        bip="$recovered_ip"
        log "Brother Scanner-IP aus bestehender Registrierung uebernommen: ${bip}"
      fi
    fi

    install_brscan4 "$baccept" "$bsrc" "$burl" "$bsha" "$blocal"
    ensure_brother_sane_links
    setup_brother_library_paths
    register_brother "$doreg" "$bname" "$bmodel" "$bip" "$bnode" "$bow"
    if [[ -n "$bip" && "$bip" != "null" ]]; then
      configure_brscan_skey "$bip"
    fi
    install_brother_button_scripts
    write_brother_button_env "$bname"

    start_brscan_skey
  else
    log "Brother Support deaktiviert"
  fi

  local primary_brother_device=""
  if [[ "$benable" == "true" ]]; then
    primary_brother_device="$(first_device_item "${DEVICES:-}")"
    if [[ -z "$primary_brother_device" && -n "${BROTHER_DEFAULT_DEVICE_RESOLVED:-}" ]]; then
      primary_brother_device="${BROTHER_DEFAULT_DEVICE_RESOLVED}"
    fi
    warmup_brother_device "$primary_brother_device"
  fi

  if command -v brsaneconfig4 >/dev/null 2>&1; then
    log_cmd_output_timeout "brsaneconfig4 -q" 5 brsaneconfig4 -q
  fi
  if command -v brscan-skey >/dev/null 2>&1; then
    log_cmd_output_timeout "brscan-skey -l" 5 brscan-skey -l
  fi
  ensure_snmp_runtime_dirs
  log_cmd_output_timeout "scanimage -L" 10 scanimage -L

  local app_dir
  if ! app_dir="$(detect_app_dir)"; then
    err "scanservjs Einstiegspunkt fehlt. Gepruefte Pfade: /usr/lib/scanservjs/server/server.js, /app/server/server.js"
    return 1
  fi

  # --- KI-Scripts starten -------------------------------------------
  if write_ai_config; then
    start_ai_cron
  else
    log "KI-Klassifikation uebersprungen (fehlende Konfiguration)"
  fi

  log "Nutze scanservjs App-Verzeichnis: ${app_dir}"
  cd "${app_dir}"
  log "Starte scanservjs"
  exec node ./server/server.js
}

main "$@"
