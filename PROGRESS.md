# Projektfortschritt — ha-scanservjs-addon

## Übersicht

| Addon | Version | Status |
|-------|---------|--------|
| scanservjs (Scanner) | 1.2.0 | ✅ Produktiv |
| scanservjs-rag (Dokumentensuche) | 1.0.2 | 🚧 In Entwicklung |

---

## scanservjs-rag — Changelog

### v1.0.2 (aktuell)
- ✅ **Dual-Watch**: Paperless-Archiv (rekursiv) + eigene Inbox
- ✅ **Enter-Taste**: on_change-Callback, zuverlässig in st.tabs
- ✅ **Suchanimation**: st.status (Spinner) + st.progress (0→33→66→100%)
- ✅ **Dokumente nach Quelle gruppiert**: Paperless / Inbox / Hochgeladen
- ✅ **Addon-Icons**: icon.png + logo.png für HA Store
- ✅ **Debian-Base**: onnxruntime-Wheel-Fix (Alpine hatte kein musl-Wheel)

### v1.0.0
- ✅ Streamlit-UI: Suche / Hochladen / Dokumente / Status
- ✅ ChromaDB embedded (/data/chromadb/)
- ✅ Ollama nomic-embed-text Embeddings
- ✅ Claude API (primär) oder Ollama LLM (Fallback)
- ✅ OCR Tesseract deu+eng, PDF/JPG/PNG/TIFF/TXT
- ✅ MD5 Duplikat-Erkennung

---

## Architektur

    Paperless archive/     /share/rag-inbox/    Direkt-Upload
          │                      │                   │
          └──────────────────────┴───────────────────┘
                                 │
                          FolderWatcher
                                 │
                   Ollama nomic-embed-text
                                 │
                            ChromaDB
                                 │
                    Claude API / Ollama LLM
                                 │
                      Streamlit (Port 7860)

---

## Offene Punkte

- [ ] Ollama installieren und Modelle pullen:
      ollama pull nomic-embed-text
      ollama pull qwen2.5:14b
- [ ] Speicher: Webtop (6GB) + Dashy (3.2GB) + Guacamole (2.3GB) löschen
- [ ] Nach Ollama-Start: Erstlauf indexiert alle Paperless-Dokumente automatisch

---

## System

| | |
|--|--|
| Hardware | i9, 20 Kerne, 32 GB RAM |
| Disk | 70.2 GB (93% voll) |
| HA | 2026.3.4 |
| Embed-Modell | nomic-embed-text |
| LLM | qwen2.5:14b oder Claude API |
| Vektordatenbank | ChromaDB embedded |
