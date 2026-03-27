#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="/data/options.json"

log() { echo "[INFO] $*"; }
err() { echo "[ERROR] $*" >&2; }

if [[ ! -f "${CONFIG_PATH}" ]]; then
    err "Keine Addon-Konfiguration unter ${CONFIG_PATH} gefunden."
    exit 1
fi

# Konfiguration als Umgebungsvariablen exportieren
export OLLAMA_URL=$(jq -r '.ollama_url // "http://homeassistant.local:11434"' "${CONFIG_PATH}")
export OLLAMA_EMBED_MODEL=$(jq -r '.ollama_embed_model // "nomic-embed-text"' "${CONFIG_PATH}")
export OLLAMA_LLM_MODEL=$(jq -r '.ollama_llm_model // "qwen2.5:14b"' "${CONFIG_PATH}")
export ANTHROPIC_API_KEY=$(jq -r '.anthropic_api_key // ""' "${CONFIG_PATH}")
export USE_CLAUDE=$(jq -r '.use_claude // false' "${CONFIG_PATH}")
export PAPERLESS_ARCHIVE=$(jq -r '.paperless_archive // "/share/paperless/media/documents/archive"' "${CONFIG_PATH}")
export INBOX_FOLDER=$(jq -r '.inbox_folder // "/share/rag-inbox"' "${CONFIG_PATH}")
export MAX_RESULTS=$(jq -r '.max_results // 5' "${CONFIG_PATH}")
export OCR_LANG=$(jq -r '.ocr_lang // "deu+eng"' "${CONFIG_PATH}")
export CHROMADB_PATH="/data/chromadb"
export UPLOAD_FOLDER="/data/uploads"

# Verzeichnisse sicherstellen
mkdir -p "${CHROMADB_PATH}" "${UPLOAD_FOLDER}"
mkdir -p "${INBOX_FOLDER}" 2>/dev/null || true

# config.yaml is copied to image root as /addon-config.yaml (Dockerfile)
ADDON_VERSION="$(grep -oE 'version:[[:space:]]*\"[^\"]+\"' /addon-config.yaml 2>/dev/null | head -n1 | sed -E 's/version:[[:space:]]*\"([^\"]+)\"/\1/' || true)"
if [[ -z "${ADDON_VERSION}" ]]; then
    ADDON_VERSION="unknown"
fi

log "Starte scanservjs-rag v${ADDON_VERSION}"
log "Ollama URL:         ${OLLAMA_URL}"
log "Embed Modell:       ${OLLAMA_EMBED_MODEL}"
log "LLM Modell:         ${OLLAMA_LLM_MODEL}"
log "Paperless Archiv:   ${PAPERLESS_ARCHIVE}"
log "Inbox Ordner:       ${INBOX_FOLDER}"
log "ChromaDB:           ${CHROMADB_PATH}"

exec streamlit run /app/app.py \
    --server.port 7860 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --browser.gatherUsageStats false
