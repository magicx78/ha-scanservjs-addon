#!/usr/bin/env bashio
set -euo pipefail

CONFIG_PATH="/data/options.json"
DELIMITER="${DELIMITER:-;}"
APP_DIR="${APP_DIR:-}"
RUNTIME_REVISION="2026-03-16-r3"

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

split_delim_lines() {
  printf "%s" "$1" | tr "${DELIMITER}" '\n' | sed '/^[[:space:]]*$/d'
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

ensure_brother_sane_links() {
  local src_dirs=("/usr/lib64/sane" "/opt/brother/scanner/brscan4")
  local dst_dirs=("/usr/lib/x86_64-linux-gnu/sane" "/usr/lib64/sane")
  local src_dir dst_dir
  local linked="false"

  for src_dir in "${src_dirs[@]}"; do
    [[ -d "$src_dir" ]] || continue
    for dst_dir in "${dst_dirs[@]}"; do
      [[ -d "$dst_dir" ]] || continue
      shopt -s nullglob
      for lib in "$src_dir"/libsane-brother*.so*; do
        ln -sf "$lib" "$dst_dir/$(basename "$lib")"
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
    if ! curl -fL --retry 3 --retry-delay 2 -o "$skey_deb" "$skey_url_legacy"; then
      warn "Legacy brscan-skey URL fehlgeschlagen, versuche aktuelle URL"
      curl -fL --retry 3 --retry-delay 2 -o "$skey_deb" "$skey_url_current"
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
  if command -v brscan-skey >/dev/null 2>&1; then
    skey_bin="$(command -v brscan-skey)"
  elif [[ -x /opt/brother/scanner/brscan-skey/brscan-skey ]]; then
    skey_bin="/opt/brother/scanner/brscan-skey/brscan-skey"
  else
    warn "brscan-skey Binary nicht gefunden."
    return 0
  fi

  if pgrep -x brscan-skey >/dev/null 2>&1; then
    log "brscan-skey laeuft bereits"
    return 0
  fi

  "${skey_bin}" >/tmp/brscan-skey.log 2>&1 &
  sleep 1

  if pgrep -x brscan-skey >/dev/null 2>&1; then
    log "brscan-skey gestartet"
  else
    warn "brscan-skey konnte nicht gestartet werden"
    [[ -f /tmp/brscan-skey.log ]] && warn "brscan-skey log: $(tail -n 20 /tmp/brscan-skey.log)"
  fi
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
    err "brother_scanner_ip fehlt. Alternativ brother_scanner_nodename setzen."
    return 1
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

main() {
  export SANED_NET_HOSTS AIRSCAN_DEVICES SCANIMAGE_LIST_IGNORE DEVICES OCR_LANG COPY_SCANS_TO

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
  COPY_SCANS_TO="$(opt '.copy_scans_to // ""')"
  local fallback_scanner_ip
  fallback_scanner_ip="$(opt '.brother_scanner_ip // ""')"

  ensure_line "airscan" "/etc/sane.d/dll.conf"

  if [[ -n "$COPY_SCANS_TO" && "$COPY_SCANS_TO" != "null" ]]; then
    log "COPY_SCANS_TO=${COPY_SCANS_TO}"
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
    ensure_generic_airscan_fallbacks "$fallback_scanner_ip"
  fi

  local benable
  benable="$(opt '.brother_enable // false')"
  if [[ "${ENABLE_BROTHER_SUPPORT}" != "true" ]]; then
    benable="false"
    log "Brother Support per ENABLE_BROTHER_SUPPORT=false deaktiviert"
  fi
  if [[ "$benable" == "true" ]]; then
    local baccept bsrc burl bsha blocal doreg bname bmodel bip bnode bow
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

    install_brscan4 "$baccept" "$bsrc" "$burl" "$bsha" "$blocal"
    ensure_brother_sane_links
    setup_brother_library_paths
    register_brother "$doreg" "$bname" "$bmodel" "$bip" "$bnode" "$bow"
    if [[ -n "$bip" && "$bip" != "null" ]]; then
      configure_brscan_skey "$bip"
    fi
    start_brscan_skey
  else
    log "Brother Support deaktiviert"
  fi

  if command -v brsaneconfig4 >/dev/null 2>&1; then
    log_cmd_output "brsaneconfig4 -q" brsaneconfig4 -q
  fi
  log_cmd_output "scanimage -L" scanimage -L

  local app_dir
  if ! app_dir="$(detect_app_dir)"; then
    err "scanservjs Einstiegspunkt fehlt. Gepruefte Pfade: /usr/lib/scanservjs/server/server.js, /app/server/server.js"
    return 1
  fi

  log "Nutze scanservjs App-Verzeichnis: ${app_dir}"
  cd "${app_dir}"
  log "Starte scanservjs"
  exec node ./server/server.js
}

main "$@"
