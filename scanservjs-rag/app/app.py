"""
scanservjs-rag — Lokale Dokumentensuche mit RAG
Streamlit Web-UI mit 4 Tabs: Suche, Hochladen, Dokumente, Status
"""

import hashlib
import os
import sys
import threading
import tempfile
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Lib-Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent))

from lib.chunker import DocumentChunker, SUPPORTED_EXTENSIONS
from lib.embedder import OllamaEmbedder
from lib.rag import RAGEngine
from lib.vector_db import VectorDB
from lib.watcher import FolderWatcher, MultiWatcher

# ---------------------------------------------------------------------------
# Konfiguration aus Umgebungsvariablen (gesetzt von run.sh)
# ---------------------------------------------------------------------------

OLLAMA_URL          = os.environ.get("OLLAMA_URL", "http://homeassistant.local:11434")
OLLAMA_EMBED_MODEL  = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_LLM_MODEL    = os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:14b")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
USE_CLAUDE          = os.environ.get("USE_CLAUDE", "false").lower() == "true"
MAX_RESULTS         = int(os.environ.get("MAX_RESULTS", "5"))
OCR_LANG            = os.environ.get("OCR_LANG", "deu+eng")
CHROMADB_PATH       = os.environ.get("CHROMADB_PATH", "/data/chromadb")
UPLOAD_FOLDER       = os.environ.get("UPLOAD_FOLDER", "/data/uploads")

# Zwei Watch-Ordner
PAPERLESS_ARCHIVE   = os.environ.get("PAPERLESS_ARCHIVE", "/share/paperless/media/documents/archive")
INBOX_FOLDER        = os.environ.get("INBOX_FOLDER", "/share/rag-inbox")

# ---------------------------------------------------------------------------
# Seitenconfig
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Dokumentensuche",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Globale Objekte (gecacht über Session-State)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_db() -> VectorDB:
    return VectorDB(persist_path=CHROMADB_PATH)


@st.cache_resource
def get_embedder() -> OllamaEmbedder:
    return OllamaEmbedder(ollama_url=OLLAMA_URL, model=OLLAMA_EMBED_MODEL)


@st.cache_resource
def get_rag() -> RAGEngine:
    return RAGEngine(
        ollama_url=OLLAMA_URL,
        llm_model=OLLAMA_LLM_MODEL,
        use_claude=USE_CLAUDE,
        anthropic_api_key=ANTHROPIC_API_KEY,
    )


@st.cache_resource
def get_multi_watcher() -> MultiWatcher:
    db = get_db()
    embedder = get_embedder()

    watchers = []

    # Watcher 1: Paperless archive (rekursiv — Unterordner nach Jahr/Monat)
    if PAPERLESS_ARCHIVE and PAPERLESS_ARCHIVE != "null":
        watchers.append(FolderWatcher(
            watch_folder=PAPERLESS_ARCHIVE,
            db=db,
            embedder=embedder,
            ocr_lang=OCR_LANG,
            source_label="paperless",
            recursive=True,
        ))

    # Watcher 2: Eigener Inbox-Ordner (flach)
    if INBOX_FOLDER and INBOX_FOLDER != "null":
        Path(INBOX_FOLDER).mkdir(parents=True, exist_ok=True)
        watchers.append(FolderWatcher(
            watch_folder=INBOX_FOLDER,
            db=db,
            embedder=embedder,
            ocr_lang=OCR_LANG,
            source_label="inbox",
            recursive=False,
        ))

    mw = MultiWatcher(watchers)
    mw.index_all_existing()   # Bestand indexieren (Background)
    mw.start_all()            # Live-Watch starten
    return mw


# Watcher beim Start initialisieren
_multi_watcher = get_multi_watcher()


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _index_file_bytes(filename: str, file_bytes: bytes) -> tuple[bool, str]:
    """Indexiert eine Datei aus Bytes. Gibt (erfolg, meldung) zurück."""
    db = get_db()
    embedder = get_embedder()
    chunker = DocumentChunker(ocr_lang=OCR_LANG)

    # Duplikat-Check
    md5 = md5_bytes(file_bytes)
    if db.is_indexed(md5):
        return False, f"'{filename}' ist bereits indexiert (Duplikat übersprungen)."

    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    try:
        chunks = chunker.chunk_file(tmp_path)
        if not chunks:
            return False, f"Kein Text aus '{filename}' extrahierbar."

        dest = Path(UPLOAD_FOLDER) / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(file_bytes)

        for c in chunks:
            c["filename"] = filename
            c["source"] = str(dest)
            c["source_label"] = "upload"
            c["md5"] = md5

        embeddings = [embedder.embed(c["text"]) for c in chunks]
        added = db.add_document(filename, chunks, embeddings)

        return True, f"'{filename}' indexiert — {added} Chunks."
    finally:
        tmp_path.unlink(missing_ok=True)


# Quelle → Icon + Label
SOURCE_ICONS = {
    "paperless": "📄 Paperless",
    "inbox":     "📥 Inbox",
    "upload":    "📤 Hochgeladen",
}

def source_label(label: str) -> str:
    return SOURCE_ICONS.get(label, f"📁 {label}")




# ---------------------------------------------------------------------------
# Pac-Man Suchanimation
# CSS wird einmalig in den DOM injiziert (eigener st.markdown-Block der
# NICHT durch st.empty() ersetzt wird) → @keyframes bleiben erhalten
# ---------------------------------------------------------------------------

_PACMAN_CSS = """
<style>
@keyframes pm-chomp {
    0%,100% { clip-path: polygon(50% 50%, 100% 12%, 100% 88%); }
    50%      { clip-path: polygon(50% 50%, 100% 50%, 100% 50%); }
}
@keyframes pm-scroll {
    from { transform: translateX(30px); }
    to   { transform: translateX(-320px); }
}
@keyframes pm-pulse {
    0%,100% { opacity: 1; } 50% { opacity: 0.35; }
}
.pm-box {
    background: #0b1623; border: 1px solid #1e3a5f;
    border-radius: 13px; padding: 18px 20px; margin: 6px 0;
}
.pm-num  { color: #60a5fa; font-size: 10px; font-weight: 800;
           letter-spacing: .12em; text-transform: uppercase; margin-bottom: 5px; }
.pm-desc { color: #e2e8f0; font-size: 15px; margin-bottom: 14px;
           animation: pm-pulse 1.5s ease infinite; }
.pm-row  { display: flex; align-items: center; height: 46px;
           overflow: hidden; margin-bottom: 12px; }
.pm-pac  {
    width: 40px; height: 40px; background: #fbbf24; border-radius: 50%;
    clip-path: polygon(50% 50%, 100% 12%, 100% 88%);
    animation: pm-chomp 0.22s linear infinite;
    flex-shrink: 0; position: relative; z-index: 2;
    box-shadow: 0 0 12px #fbbf2488;
}
.pm-track {
    display: flex; align-items: center; gap: 18px;
    animation: pm-scroll 1.7s linear infinite;
    padding-left: 10px; flex: 1;
}
.pm-dot { width: 9px; height: 9px; background: #60a5fa;
          border-radius: 50%; box-shadow: 0 0 6px #60a5faaa; flex-shrink: 0; }
.pm-doc { width: 8px; height: 10px; background: #93c5fd;
          border-radius: 1px 3px 1px 1px;
          box-shadow: 0 0 6px #93c5fdaa; flex-shrink: 0; }
.pm-bar-bg   { height: 5px; background: #1e3a5f; border-radius: 3px; overflow: hidden; }
.pm-bar-fill { height: 100%;
               background: linear-gradient(90deg, #b45309, #f59e0b, #fbbf24);
               border-radius: 3px; transition: width .45s ease; }
.pm-done {
    display: flex; align-items: center; gap: 12px;
    background: #052e16; border: 1px solid #166534;
    border-radius: 13px; padding: 14px 20px;
    color: #86efac; font-weight: 700; font-size: 15px;
}
</style>
"""

_DOTS = "".join(['<div class="pm-doc"></div><div class="pm-dot"></div>'] * 12)


def _pacman_step(step: int, total: int, desc: str, pct: int) -> str:
    return f"""
<div class="pm-box">
  <div class="pm-num">Schritt {step} / {total}</div>
  <div class="pm-desc">{desc}</div>
  <div class="pm-row">
    <div class="pm-pac"></div>
    <div class="pm-track">{_DOTS}</div>
  </div>
  <div class="pm-bar-bg"><div class="pm-bar-fill" style="width:{pct}%"></div></div>
</div>"""


def _pacman_done() -> str:
    return """<div class="pm-done">
  <span style="font-size:24px">😊</span>
  Alle Daten verarbeitet — Antwort bereit!
</div>"""


# ---------------------------------------------------------------------------
# Tab 1: Suche
# ---------------------------------------------------------------------------

def _on_search_enter():
    """Wird bei Enter im Suchfeld aufgerufen."""
    q = st.session_state.get("search_q", "").strip()
    if q:
        st.session_state["_do_search"] = True


def tab_suche():
    st.header("Dokumentensuche")

    db = get_db()
    stats = db.get_stats()
    if stats["total_documents"] == 0:
        st.info("Noch keine Dokumente indexiert. Paperless-Archiv und Inbox werden automatisch überwacht.")
        return

    st.caption(f"{stats['total_documents']} Dokumente · {stats['total_chunks']} Chunks indexiert")

    # Eingabezeile: Enter-Taste via on_change, Button als Alternative
    col_input, col_btn = st.columns([6, 1])
    with col_input:
        question = st.text_input(
            "Frage stellen",
            placeholder="z.B. Welche Rechnungen gibt es von 2024? — dann Enter ↵",
            key="search_q",
            on_change=_on_search_enter,
            label_visibility="collapsed",
        )
    with col_btn:
        if st.button("🔍 Suchen", type="primary", use_container_width=True):
            if question.strip():
                st.session_state["_do_search"] = True

    do_search = st.session_state.pop("_do_search", False)

    # CSS einmalig injizieren (eigener DOM-Knoten, wird nicht überschrieben)
    st.markdown(_PACMAN_CSS, unsafe_allow_html=True)

    if do_search and question.strip():
        embedder   = get_embedder()
        rag        = get_rag()
        model_name = "Claude API" if USE_CLAUDE else OLLAMA_LLM_MODEL
        anim       = st.empty()

        # Schritt 1 — Pac-Man frisst Vektoren
        anim.markdown(_pacman_step(1, 3, "Frage in Vektor-Embedding umwandeln …", 15),
                      unsafe_allow_html=True)
        query_emb = embedder.embed(question)
        if not query_emb:
            anim.error("❌ Embedding fehlgeschlagen — ist Ollama erreichbar?")
            return

        # Schritt 2 — Pac-Man frisst Dokumente
        anim.markdown(_pacman_step(2, 3, "Ähnliche Dokumente in ChromaDB suchen …", 50),
                      unsafe_allow_html=True)
        chunks = db.search(query_emb, n_results=MAX_RESULTS)

        # Schritt 3 — Pac-Man frisst Tokens
        anim.markdown(_pacman_step(3, 3, f"Antwort generieren mit {model_name} …", 80),
                      unsafe_allow_html=True)
        st.markdown("### Antwort")
        answer_box = st.empty()
        answer = rag.answer(question, chunks, stream_placeholder=answer_box)

        # Fertig — satter Pac-Man
        anim.markdown(_pacman_done(), unsafe_allow_html=True)

        if chunks:
            st.markdown("### Quellen")
            for i, chunk in enumerate(chunks, start=1):
                rel   = chunk.get("relevance_score", 0)
                fname = chunk.get("filename", "?")
                page  = chunk.get("page", "?")
                src   = source_label(chunk.get("source_label", ""))
                with st.expander(f"Quelle {i}: {fname} — Seite {page} · {src} (Relevanz {rel:.0%})"):
                    st.text(chunk.get("text", ""))


# ---------------------------------------------------------------------------
# Tab 2: Hochladen
# ---------------------------------------------------------------------------

def tab_hochladen():
    st.header("Dokument hochladen & indexieren")

    st.info(
        f"**Automatisch überwacht:**\n"
        f"- 📄 Paperless-Archiv: `{PAPERLESS_ARCHIVE}`\n"
        f"- 📥 Inbox: `{INBOX_FOLDER}`\n\n"
        f"Oder hier direkt hochladen:"
    )

    ext_list = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    st.caption(f"Unterstützte Formate: {ext_list}")

    uploaded_files = st.file_uploader(
        "Dateien auswählen",
        type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
        key="uploader",
    )

    if uploaded_files:
        if st.button("Alle indexieren", type="primary"):
            for uf in uploaded_files:
                file_bytes = uf.read()
                with st.status(f"Verarbeite '{uf.name}'...", expanded=True) as status:
                    st.write("Chunking + OCR...")
                    success, msg = _index_file_bytes(uf.name, file_bytes)
                    if success:
                        status.update(label=f"'{uf.name}' — fertig", state="complete")
                        st.success(msg)
                    else:
                        status.update(label=f"'{uf.name}' — übersprungen", state="error")
                        st.warning(msg)


# ---------------------------------------------------------------------------
# Tab 3: Dokumente
# ---------------------------------------------------------------------------

def tab_dokumente():
    st.header("Indexierte Dokumente")

    db = get_db()
    docs = db.list_documents()

    if not docs:
        st.info("Keine Dokumente indexiert.")
        return

    # Gruppierung nach Quelle
    by_source: dict[str, list] = {}
    for doc in docs:
        lbl = doc.get("source_label", "unbekannt")
        by_source.setdefault(lbl, []).append(doc)

    st.caption(f"{len(docs)} Dokumente insgesamt")

    for lbl, group in by_source.items():
        with st.expander(f"{source_label(lbl)} ({len(group)} Dokumente)", expanded=True):
            for doc in group:
                col1, col2, col3 = st.columns([5, 2, 1])
                with col1:
                    st.text(f"{doc['filename']} ({doc['chunk_count']} Chunks)")
                with col2:
                    file_path = Path(doc.get("source", ""))
                    if not file_path.exists():
                        alt_path = Path(UPLOAD_FOLDER) / doc["filename"]
                        if alt_path.exists():
                            file_path = alt_path

                    if file_path.exists():
                        with open(file_path, "rb") as f:
                            st.download_button(
                                label="Download",
                                data=f.read(),
                                file_name=doc["filename"],
                                key=f"dl_{lbl}_{doc['filename']}",
                            )
                    else:
                        st.caption("Datei nicht lokal")
                with col3:
                    if st.button("🗑", key=f"del_{lbl}_{doc['filename']}", help="Löschen"):
                        deleted = db.delete_document(doc["filename"])
                        st.success(f"{doc['filename']} gelöscht ({deleted} Chunks).")
                        st.rerun()


# ---------------------------------------------------------------------------
# Tab 4: Status
# ---------------------------------------------------------------------------

def tab_status():
    st.header("System-Status")

    embedder = get_embedder()
    db = get_db()

    # Ollama Status
    st.subheader("Ollama")
    ok, msg = embedder.check_connection()
    if ok:
        st.success(f"Verbunden: {OLLAMA_URL}")
        st.caption(msg)
    else:
        st.error(f"Nicht erreichbar: {OLLAMA_URL}")
        st.caption(msg)

    models = embedder.list_models()
    if models:
        with st.expander(f"Verfügbare Modelle ({len(models)})"):
            for m in models:
                icon = "✓" if m in (OLLAMA_EMBED_MODEL, OLLAMA_LLM_MODEL) else " "
                st.text(f"{icon} {m}")

    st.divider()

    # Watcher Status
    st.subheader("Watch-Ordner")
    for w in _multi_watcher.watchers:
        status = "🟢 aktiv" if w.is_running else "🔴 inaktiv"
        icon = SOURCE_ICONS.get(w._source_label, w._source_label)
        st.text(f"{status}  {icon}: {w._watch_folder}")

    st.divider()

    # Indexierung
    st.subheader("Indexierung")
    col1, col2 = st.columns([2, 3])
    with col1:
        if st.button("🔄 Neu indexieren", type="primary", use_container_width=True):
            _multi_watcher.reindex()
            st.success("Gestartet — neue Dokumente erscheinen in wenigen Minuten.")
    with col2:
        st.caption("Nützlich nach Ollama-URL-Änderung oder wenn Dokumente fehlen.")

    st.divider()

    # ChromaDB Stats + Reset
    st.subheader("Datenbank (ChromaDB)")
    stats = db.get_stats()
    col1, col2, col3 = st.columns(3)
    col1.metric("Dokumente", stats["total_documents"])
    col2.metric("Chunks", stats["total_chunks"])
    col3.metric("Speicher", f"{stats['db_size_mb']} MB")

    st.write("")
    if "confirm_reset" not in st.session_state:
        st.session_state.confirm_reset = False

    if not st.session_state.confirm_reset:
        if st.button("🗑️ Datenbank leeren", type="secondary"):
            st.session_state.confirm_reset = True
            st.rerun()
    else:
        st.warning(f"⚠️ Alle {stats['total_documents']} Dokumente werden unwiderruflich gelöscht!")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Ja, alles löschen", type="primary", use_container_width=True):
                deleted = db.reset()
                st.cache_resource.clear()
                st.session_state.confirm_reset = False
                st.success(f"Datenbank geleert — {deleted} Chunks gelöscht.")
                st.rerun()
        with col2:
            if st.button("Abbrechen", use_container_width=True):
                st.session_state.confirm_reset = False
                st.rerun()

    st.divider()

    # Konfiguration
    st.subheader("Konfiguration")
    config_data = {
        "Ollama URL":           OLLAMA_URL,
        "Embedding-Modell":     OLLAMA_EMBED_MODEL,
        "LLM-Modell":           OLLAMA_LLM_MODEL,
        "LLM-Modus":            "Claude API" if USE_CLAUDE else f"Ollama ({OLLAMA_LLM_MODEL})",
        "Paperless-Archiv":     PAPERLESS_ARCHIVE,
        "Inbox-Ordner":         INBOX_FOLDER,
        "OCR-Sprachen":         OCR_LANG,
        "Max. Ergebnisse":      str(MAX_RESULTS),
        "ChromaDB-Pfad":        CHROMADB_PATH,
    }
    for key, val in config_data.items():
        col1, col2 = st.columns([2, 3])
        col1.caption(key)
        col2.text(val)


# ---------------------------------------------------------------------------
# Haupt-Layout
# ---------------------------------------------------------------------------

st.title("🔍 Dokumentensuche")

tab1, tab2, tab3, tab4 = st.tabs(["💬 Suche", "📤 Hochladen", "📁 Dokumente", "⚙️ Status"])

with tab1:
    tab_suche()

with tab2:
    tab_hochladen()

with tab3:
    tab_dokumente()

with tab4:
    tab_status()
