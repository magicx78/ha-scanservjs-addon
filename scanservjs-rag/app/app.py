"""
scanservjs-rag - local document search with progressive RAG UX.
"""

import hashlib
import html
import logging
import os
import queue
import base64
import sys
import tempfile
import threading
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent))

from lib.chunker import DocumentChunker, SUPPORTED_EXTENSIONS
from lib.embedder import OllamaEmbedder
from lib.rag import RAGEngine
from lib.search_service import SearchService
from lib.search_cache import PersistentSearchCache
from lib.vector_db import VectorDB
from lib.watcher import FolderWatcher, MultiWatcher
from lib.state_machine import normalize_transition

logger = logging.getLogger("scanservjs-rag")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://homeassistant.local:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_LLM_MODEL = os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:14b")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
USE_CLAUDE = os.environ.get("USE_CLAUDE", "false").lower() == "true"
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "5"))
OCR_LANG = os.environ.get("OCR_LANG", "deu+eng")
CHROMADB_PATH = os.environ.get("CHROMADB_PATH", "/data/chromadb")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "/data/uploads")
PAPERLESS_ARCHIVE = os.environ.get(
    "PAPERLESS_ARCHIVE", "/share/paperless/media/documents/archive"
)
INBOX_FOLDER = os.environ.get("INBOX_FOLDER", "/share/rag-inbox")
SEARCH_CACHE_TTL_SECONDS = int(os.environ.get("SEARCH_CACHE_TTL_SECONDS", "180"))
SEARCH_CACHE_DB_PATH = os.environ.get("SEARCH_CACHE_DB_PATH", "/data/search_cache.sqlite")
SEARCH_CACHE_MAX_ENTRIES = int(os.environ.get("SEARCH_CACHE_MAX_ENTRIES", "300"))
STREAM_MAX_RETRIES = int(os.environ.get("STREAM_MAX_RETRIES", "3"))
STREAM_RETRY_BASE_SECONDS = float(os.environ.get("STREAM_RETRY_BASE_SECONDS", "0.4"))
STREAM_RETRY_JITTER_SECONDS = float(os.environ.get("STREAM_RETRY_JITTER_SECONDS", "0.25"))
ENABLE_REFINE = os.environ.get("ENABLE_REFINE", "false").lower() == "true"
USE_SEARCH_STREAMING = os.environ.get("USE_SEARCH_STREAMING", "true").lower() == "true"

SEARCH_PHASE_ORDER = [
    "started",
    "retrieving",
    "reranking",
    "generating_answer",
    "done",
]
TERMINAL_PHASES = {"done", "error"}

SOURCE_ICONS = {
    "paperless": "Paperless",
    "inbox": "Inbox",
    "upload": "Upload",
}

PHASE_LABELS = {
    "idle": "Bereit",
    "started": "Suche gestartet",
    "retrieving": "Treffer werden geladen",
    "reranking": "Treffer werden sortiert",
    "generating_answer": "Antwort wird aufgebaut",
    "done": "Abgeschlossen",
    "error": "Fehler",
}

STATUS_DESCRIPTIONS = {
    "idle": "Bereit fuer neue Suche.",
    "started": "Anfrage initialisiert und Suchlauf vorbereitet.",
    "retrieving": "Treffer werden semantisch ermittelt.",
    "reranking": "Treffer werden nach Relevanz final sortiert.",
    "generating_answer": "Antwort wird live aus Treffern erzeugt.",
    "done": "Suchlauf ist abgeschlossen.",
    "error": "Die Verarbeitung wurde mit Fehler beendet.",
}

DESIGN_CSS = """
<style>
:root {
  color-scheme: dark;
  --bg: #070d16;
  --surface: #111a28;
  --surface-strong: #1a2638;
  --text: #e8effa;
  --muted: #a8b7cb;
  --line: #2a3a52;
  --accent: #63a5ff;
  --ok: #52d08f;
  --warn: #f6ba63;
  --err: #ff8a7e;
  --radius: 14px;
  --radius-sm: 10px;
}
.stApp {
  background: radial-gradient(circle at 5% 0%, rgba(19,102,214,0.06), transparent 28%), var(--bg);
  color: var(--text);
}
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"],
[data-testid="stSidebar"],
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"] {
  background: var(--bg) !important;
  color: var(--text) !important;
}
[data-testid="stDialog"] > div,
[data-testid="stDialog"] [role="dialog"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--line) !important;
}
[data-testid="stTabs"] [role="tab"] {
  background: var(--surface) !important;
  color: var(--muted) !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px 10px 0 0 !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  background: color-mix(in srgb, var(--accent) 16%, var(--surface)) !important;
  color: var(--text) !important;
  border-color: color-mix(in srgb, var(--accent) 45%, var(--line)) !important;
}
[data-testid="stExpander"] details {
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  border-radius: var(--radius-sm) !important;
}
[data-testid="stExpander"] summary {
  color: var(--text) !important;
}
[data-baseweb="input"] > div,
[data-baseweb="textarea"] > div,
[data-baseweb="select"] > div {
  background: var(--surface) !important;
  border-color: var(--line) !important;
}
[data-baseweb="input"] input,
[data-baseweb="textarea"] textarea,
[data-baseweb="select"] input,
[data-baseweb="select"] [role="combobox"] {
  color: var(--text) !important;
}
[data-baseweb="popover"],
[role="listbox"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--line) !important;
}
[role="option"] {
  color: var(--text) !important;
}
[role="option"][aria-selected="true"] {
  background: color-mix(in srgb, var(--accent) 20%, var(--surface)) !important;
}
.stButton > button,
.stDownloadButton > button {
  background: var(--surface-strong) !important;
  color: var(--text) !important;
  border: 1px solid var(--line) !important;
  border-radius: 10px !important;
}
.stButton > button:hover,
.stDownloadButton > button:hover {
  border-color: color-mix(in srgb, var(--accent) 55%, var(--line)) !important;
  color: #f7fbff !important;
}
.stButton > button[data-testid="baseButton-primary"] {
  background: linear-gradient(120deg, #2a6fd6, #4f90eb) !important;
  color: #f7fbff !important;
  border-color: #4f90eb !important;
}
[data-testid="stAlert"] {
  background: color-mix(in srgb, var(--surface) 92%, var(--accent)) !important;
  color: var(--text) !important;
  border: 1px solid var(--line) !important;
}
[data-testid="stMetric"] {
  background: var(--surface) !important;
  border: 1px solid var(--line) !important;
  border-radius: var(--radius-sm) !important;
  padding: .5rem .65rem !important;
}
[data-testid="stCaptionContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
label,
p,
h1,
h2,
h3,
h4 {
  color: var(--text) !important;
}
.glass-card {
  background: linear-gradient(180deg, var(--surface), var(--surface-strong));
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 1rem 1.1rem;
}
.status-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: .45rem;
}
.status-chip {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: .35rem .65rem;
  font-size: .78rem;
  color: var(--muted);
  background: var(--surface);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.status-chip.done {
  border-color: color-mix(in srgb, var(--ok) 55%, var(--line));
  color: var(--ok);
}
.status-chip.active {
  border-color: color-mix(in srgb, var(--accent) 65%, var(--line));
  color: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 18%, transparent);
  animation: pulse-chip 1.25s ease-in-out infinite;
}
.status-chip.problem {
  border-color: color-mix(in srgb, var(--err) 50%, var(--line));
  color: var(--err);
}
.meta-line {
  color: var(--muted);
  font-size: .86rem;
  margin-top: .3rem;
}
.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: .65rem;
}
.result-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: .72rem .82rem;
  background: var(--surface);
  transform: translateY(0);
  opacity: 1;
  transition: transform .22s ease, opacity .22s ease;
}
.result-title {
  font-weight: 650;
  color: var(--text);
  font-size: .9rem;
}
.result-sub {
  color: var(--muted);
  font-size: .78rem;
  margin-top: .22rem;
}
.result-snippet {
  color: var(--text);
  font-size: .82rem;
  margin-top: .45rem;
  line-height: 1.34;
  max-height: 5.2rem;
  overflow: hidden;
}
.results-box {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface);
  padding: .85rem .95rem;
  max-height: 45vh;
  overflow: auto;
}
.hit-item {
  border-left: 3px solid color-mix(in srgb, var(--accent) 65%, var(--line));
  padding: .42rem .62rem;
  margin: .5rem 0;
  border-radius: 6px;
  background: color-mix(in srgb, var(--surface) 88%, var(--accent));
  animation: hit-pop .22s ease;
}
.spark {
  display: inline-block;
  width: .42rem;
  height: .42rem;
  border-radius: 50%;
  background: var(--accent);
  margin-left: .22rem;
  animation: spark 1.1s ease-in-out infinite;
}
.spark:nth-child(2) { animation-delay: .14s; }
.spark:nth-child(3) { animation-delay: .28s; }
.answer-box {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface);
  padding: .92rem;
  min-height: 6rem;
  max-height: 55vh;
  overflow: auto;
  line-height: 1.45;
  word-break: break-word;
}
.answer-streaming::after {
  content: "";
  display: inline-block;
  width: .55rem;
  height: 1rem;
  margin-left: .28rem;
  background: var(--accent);
  animation: blink .9s steps(1, end) infinite;
}
.skeleton {
  border-radius: 8px;
  background: linear-gradient(90deg, rgba(140,159,184,0.14) 20%, rgba(140,159,184,0.28) 50%, rgba(140,159,184,0.14) 80%);
  background-size: 280% 100%;
  animation: shimmer 1.25s linear infinite;
}
.skeleton.line { height: .8rem; margin-bottom: .45rem; }
.skeleton.line.short { width: 55%; }
.callout {
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 84%, var(--accent));
  border-radius: var(--radius-sm);
  padding: .66rem .78rem;
  font-size: .85rem;
  color: var(--text);
}
@keyframes blink { 50% { opacity: 0; } }
@keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@keyframes pulse-chip { 50% { transform: translateY(-1px); } }
@keyframes hit-pop { from { transform: translateY(4px); opacity: .4; } to { transform: translateY(0); opacity: 1; } }
@keyframes spark { 0%,100% { transform: translateY(0); opacity: .25; } 50% { transform: translateY(-3px); opacity: 1; } }
@keyframes pac-chomp { 0%,100% { clip-path: polygon(50% 50%, 100% 15%, 100% 85%);} 50% { clip-path: polygon(50% 50%, 100% 50%, 100% 50%);} }
.pacman-row {
  display: flex;
  align-items: center;
  gap: .55rem;
  margin-bottom: .55rem;
  color: var(--muted);
  font-size: .82rem;
}
.pacman {
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #f7b733;
  font-size: 18px;
  font-weight: 700;
  animation: pac-run .55s ease-in-out infinite;
  text-shadow: 0 0 10px rgba(247,183,51,.45);
}
.pacman-dots {
  display: inline-flex;
  gap: .26rem;
}
.pacman-dot {
  width: .28rem;
  height: .28rem;
  border-radius: 50%;
  background: color-mix(in srgb, var(--accent) 70%, var(--line));
  animation: spark .9s ease-in-out infinite;
}
.pacman-dot:nth-child(2) { animation-delay: .12s; }
.pacman-dot:nth-child(3) { animation-delay: .24s; }
@keyframes pac-run { 0%,100% { transform: translateX(0); } 50% { transform: translateX(2px); } }
.live-row {
  display: flex;
  align-items: center;
  gap: .4rem;
  color: var(--muted);
  font-size: .8rem;
  margin-bottom: .4rem;
}
.preview-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: .5rem;
  margin-bottom: .7rem;
}
.preview-meta-item {
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 90%, var(--accent));
  border-radius: 9px;
  padding: .45rem .55rem;
  min-height: 3.1rem;
}
.preview-meta-label {
  color: var(--muted);
  font-size: .74rem;
  line-height: 1.2;
}
.preview-meta-value {
  color: var(--text);
  font-size: .82rem;
  font-weight: 580;
  margin-top: .2rem;
  word-break: break-word;
}
.preview-frame {
  width: 100%;
  min-height: 56vh;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #0b121c;
}
.preview-actions {
  margin: .45rem 0 .7rem;
}
@media (max-width: 900px) {
  .preview-frame {
    min-height: 66vh;
  }
}
</style>
"""

st.set_page_config(
    page_title="Dokumentensuche",
    page_icon="ðŸ”Ž",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(DESIGN_CSS, unsafe_allow_html=True)


@st.cache_resource
def get_db() -> VectorDB:
    return VectorDB(persist_path=CHROMADB_PATH)


@st.cache_data(ttl=3)
def get_db_stats_cached() -> dict:
    return get_db().get_stats()


@st.cache_data(ttl=5)
def list_documents_cached() -> list[dict]:
    return get_db().list_documents()


@st.cache_resource
def get_persistent_search_cache() -> PersistentSearchCache:
    return PersistentSearchCache(
        db_path=SEARCH_CACHE_DB_PATH,
        ttl_seconds=SEARCH_CACHE_TTL_SECONDS,
        max_entries=SEARCH_CACHE_MAX_ENTRIES,
    )


def invalidate_ui_caches():
    """Invalidate data caches after write operations."""
    st.cache_data.clear()
    if "search_state" in st.session_state:
        st.session_state.search_state["search_cache"] = {}
    try:
        get_persistent_search_cache().invalidate_all()
    except Exception:
        pass


@st.cache_resource
def get_embedder() -> OllamaEmbedder:
    return OllamaEmbedder(ollama_url=OLLAMA_URL, model=OLLAMA_EMBED_MODEL)


@st.cache_resource
def get_rag(llm_model: str = OLLAMA_LLM_MODEL) -> RAGEngine:
    return RAGEngine(
        ollama_url=OLLAMA_URL,
        llm_model=llm_model,
        use_claude=USE_CLAUDE,
        anthropic_api_key=ANTHROPIC_API_KEY,
        max_retries=STREAM_MAX_RETRIES,
        retry_base_seconds=STREAM_RETRY_BASE_SECONDS,
        retry_jitter_seconds=STREAM_RETRY_JITTER_SECONDS,
    )


@st.cache_resource
def get_multi_watcher() -> MultiWatcher:
    db = get_db()
    embedder = get_embedder()
    watchers = []

    if PAPERLESS_ARCHIVE and PAPERLESS_ARCHIVE != "null":
        try:
            watchers.append(
                FolderWatcher(
                    watch_folder=PAPERLESS_ARCHIVE,
                    db=db,
                    embedder=embedder,
                    ocr_lang=OCR_LANG,
                    source_label="paperless",
                    recursive=True,
                )
            )
        except Exception as exc:
            logger.exception("Paperless-Watcher konnte nicht erstellt werden: %s", exc)

    if INBOX_FOLDER and INBOX_FOLDER != "null":
        try:
            Path(INBOX_FOLDER).mkdir(parents=True, exist_ok=True)
            watchers.append(
                FolderWatcher(
                    watch_folder=INBOX_FOLDER,
                    db=db,
                    embedder=embedder,
                    ocr_lang=OCR_LANG,
                    source_label="inbox",
                    recursive=False,
                )
            )
        except Exception as exc:
            logger.exception("Inbox-Watcher konnte nicht erstellt werden: %s", exc)

    multi = MultiWatcher(watchers)
    try:
        multi.index_all_existing()
    except Exception as exc:
        logger.exception("Indexierung beim Start fehlgeschlagen: %s", exc)
    try:
        multi.start_all()
    except Exception as exc:
        logger.exception("Watcher-Start fehlgeschlagen: %s", exc)
    return multi


try:
    _multi_watcher = get_multi_watcher()
except Exception as exc:
    logger.exception("Watcher-Initialisierung komplett fehlgeschlagen: %s", exc)
    _multi_watcher = MultiWatcher([])


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def source_label(label: str) -> str:
    return SOURCE_ICONS.get(label, f"Quelle: {label}")


def _hit_widget_key(prefix: str, index: int, hit: dict) -> str:
    raw = (
        f"{prefix}|{index}|{hit.get('filename','')}|{hit.get('page',1)}|"
        f"{hit.get('chunk_index',0)}|{hit.get('source','')}"
    )
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _next_render_nonce(name: str) -> int:
    key = f"_{name}_render_nonce"
    current = int(st.session_state.get(key, 0)) + 1
    st.session_state[key] = current
    return current


def _resolve_hit_file(hit: dict) -> Path | None:
    candidates: list[Path] = []
    source_path = (hit.get("source") or "").strip()
    filename = (hit.get("filename") or "").strip()
    if source_path:
        candidates.append(Path(source_path))
    if filename:
        candidates.append(Path(UPLOAD_FOLDER) / filename)

    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except Exception:
            continue
    return None


def _open_preview_for_hit(hit: dict):
    st.session_state["preview_hit"] = {
        "filename": hit.get("filename", ""),
        "page": int(hit.get("page", 1) or 1),
        "chunk_index": int(hit.get("chunk_index", 0) or 0),
        "source": hit.get("source", ""),
        "source_label": hit.get("source_label", ""),
        "relevance_score": float(hit.get("relevance_score", 0.0) or 0.0),
        "text": hit.get("text", "") or "",
    }
    st.session_state["preview_open"] = True


def _close_preview():
    st.session_state["preview_open"] = False
    st.session_state["preview_hit"] = None


def _open_doc_download(path: str, filename: str):
    st.session_state["doc_download_path"] = path
    st.session_state["doc_download_filename"] = filename
    st.session_state["doc_download_open"] = True


def _close_doc_download():
    st.session_state["doc_download_open"] = False
    st.session_state["doc_download_path"] = ""
    st.session_state["doc_download_filename"] = ""


@st.cache_data(ttl=300, show_spinner=False)
def _load_binary_file(path: str) -> bytes:
    return Path(path).read_bytes()


def _render_preview_actions(pdf_data_uri: str, filename: str):
    st.markdown("<div class='preview-actions'></div>", unsafe_allow_html=True)
    action_left, action_mid, action_right = st.columns([1, 1, 1])
    safe_filename = html.escape(filename, quote=True)
    with action_left:
        components.html(
            f"""
            <div style="height:40px;display:flex;align-items:center;">
              <button
                style="
                  width:100%;
                  height:36px;
                  border-radius:10px;
                  border:1px solid #2a3a52;
                  background:#1a2638;
                  color:#e8effa;
                  font-weight:600;
                  cursor:pointer;"
                onclick="const w = window.open('{pdf_data_uri}', '_blank'); if (w) {{ w.focus(); setTimeout(() => w.print(), 450); }}">
                Drucken
              </button>
            </div>
            """,
            height=44,
        )
    with action_mid:
        components.html(
            f"""
            <div style="height:40px;display:flex;align-items:center;">
              <a
                download="{safe_filename}"
                href="{pdf_data_uri}"
                style="
                  width:100%;
                  height:36px;
                  border-radius:10px;
                  border:1px solid #2a3a52;
                  background:#1a2638;
                  color:#e8effa;
                  font-weight:600;
                  text-decoration:none;
                  display:flex;
                  align-items:center;
                  justify-content:center;">
                Speichern / Download
              </a>
            </div>
            """,
            height=44,
        )
    with action_right:
        if st.button("Schliessen", use_container_width=True, key="preview_close_btn"):
            _close_preview()
            st.rerun()


@st.dialog("Dokumentvorschau", width="large")
def _render_preview_dialog():
    hit = st.session_state.get("preview_hit") or {}
    if not hit:
        st.info("Kein Treffer ausgewaehlt.")
        return

    rel = max(0.0, min(1.0, float(hit.get("relevance_score", 0.0) or 0.0)))
    page = int(hit.get("page", 1) or 1)
    chunk_index = int(hit.get("chunk_index", 0) or 0)
    src_label = source_label(hit.get("source_label", ""))

    st.markdown(
        "<div class='preview-meta-grid'>"
        "<div class='preview-meta-item'>"
        "<div class='preview-meta-label'>Dokumentname</div>"
        f"<div class='preview-meta-value'>{html.escape(hit.get('filename', '-'))}</div>"
        "</div>"
        "<div class='preview-meta-item'>"
        "<div class='preview-meta-label'>Seite / Chunk</div>"
        f"<div class='preview-meta-value'>Seite {page} · Chunk {chunk_index}</div>"
        "</div>"
        "<div class='preview-meta-item'>"
        "<div class='preview-meta-label'>Quelle</div>"
        f"<div class='preview-meta-value'>{html.escape(src_label)}</div>"
        "</div>"
        "<div class='preview-meta-item'>"
        "<div class='preview-meta-label'>Relevanz</div>"
        f"<div class='preview-meta-value'>{rel:.0%}</div>"
        "</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    file_path = _resolve_hit_file(hit)
    if not file_path:
        st.error("Datei fuer Vorschau nicht gefunden. Bitte Quelle/Upload pruefen.")
        if st.button("Schliessen", use_container_width=True, key="preview_close_missing"):
            _close_preview()
            st.rerun()
        return

    suffix = file_path.suffix.lower()
    if suffix != ".pdf":
        st.warning(f"Datei ist kein PDF ({file_path.name}). Download ist weiterhin moeglich.")
        file_bytes = _load_binary_file(str(file_path))
        non_pdf_b64 = base64.b64encode(file_bytes).decode("ascii")
        non_pdf_uri = f"data:application/octet-stream;base64,{non_pdf_b64}"
        safe_filename = html.escape(file_path.name, quote=True)
        components.html(
            f"""
            <div style="height:44px;display:flex;align-items:center;">
              <a
                download="{safe_filename}"
                href="{non_pdf_uri}"
                style="
                  width:100%;
                  height:36px;
                  border-radius:10px;
                  border:1px solid #2a3a52;
                  background:#1a2638;
                  color:#e8effa;
                  font-weight:600;
                  text-decoration:none;
                  display:flex;
                  align-items:center;
                  justify-content:center;">
                Speichern / Download
              </a>
            </div>
            """,
            height=48,
        )
        if st.button("Schliessen", use_container_width=True, key="preview_close_nonpdf"):
            _close_preview()
            st.rerun()
        return

    file_bytes = _load_binary_file(str(file_path))
    b64 = base64.b64encode(file_bytes).decode("ascii")
    pdf_data_uri = f"data:application/pdf;base64,{b64}"
    iframe_src = f"{pdf_data_uri}#page={max(1, page)}&view=FitH&toolbar=1&navpanes=0"

    _render_preview_actions(pdf_data_uri=pdf_data_uri, filename=file_path.name)
    st.markdown(f"<iframe class='preview-frame' src='{iframe_src}'></iframe>", unsafe_allow_html=True)

    snippet = (hit.get("text", "") or "").strip()
    if snippet:
        st.caption(f"Treffer-Auszug: {snippet[:420]}")


def _maybe_open_preview_dialog():
    if st.session_state.get("preview_open", False):
        _render_preview_dialog()


@st.dialog("Dokument-Download", width="medium")
def _render_doc_download_dialog():
    path = (st.session_state.get("doc_download_path") or "").strip()
    filename = (st.session_state.get("doc_download_filename") or "").strip() or "dokument.bin"
    if not path:
        st.error("Kein Dokument fuer Download gesetzt.")
        if st.button("Schliessen", key="doc_dl_close_empty", use_container_width=True):
            _close_doc_download()
            st.rerun()
        return

    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        st.error("Datei nicht gefunden.")
        if st.button("Schliessen", key="doc_dl_close_missing", use_container_width=True):
            _close_doc_download()
            st.rerun()
        return

    data = _load_binary_file(str(file_path))
    suffix = file_path.suffix.lower()
    mime = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
    b64 = base64.b64encode(data).decode("ascii")
    uri = f"data:{mime};base64,{b64}"
    safe_filename = html.escape(filename, quote=True)
    components.html(
        f"""
        <div style="display:flex;align-items:center;gap:.5rem;margin:.25rem 0 .75rem;">
          <a
            download="{safe_filename}"
            href="{uri}"
            style="
              width:100%;
              height:36px;
              border-radius:10px;
              border:1px solid #2a3a52;
              background:#1a2638;
              color:#e8effa;
              font-weight:600;
              text-decoration:none;
              display:flex;
              align-items:center;
              justify-content:center;">
            Download starten
          </a>
        </div>
        """,
        height=56,
    )
    if st.button("Schliessen", key="doc_dl_close", use_container_width=True):
        _close_doc_download()
        st.rerun()


def _maybe_open_doc_download_dialog():
    if st.session_state.get("doc_download_open", False):
        _render_doc_download_dialog()


def _render_llm_selector(prefix: str = "search"):
    embedder = get_embedder()
    models = embedder.list_chat_models()
    current_llm = st.session_state.get("llm_model", OLLAMA_LLM_MODEL)

    if not models:
        fallback_models = embedder.list_models()
        if fallback_models:
            models = fallback_models
            st.warning(
                "Konnte chatfaehige Modelle nicht sicher erkennen. "
                "Bitte nur LLM-Modelle (keine Embedding-Modelle) auswaehlen."
            )
        else:
            st.error("LLM-Modelle konnten nicht geladen werden (Ollama offline?).")
            return current_llm, False

    if current_llm not in models:
        current_llm = models[0]
        st.session_state["llm_model"] = current_llm

    idx = models.index(current_llm)
    selected = st.selectbox(
        "LLM-Modell",
        options=models,
        index=idx,
        key=f"{prefix}_llm_select",
        help="Wird sofort für die nächste Antwort verwendet.",
    )
    if selected != st.session_state.get("llm_model"):
        st.session_state["llm_model"] = selected

    is_online = selected in models
    if is_online:
        st.caption(f"Modellstatus: online · aktiv: {selected}")
    else:
        st.caption(f"Modellstatus: nicht verfügbar · gewählt: {selected}")
    return selected, is_online


def _index_file_bytes(filename: str, file_bytes: bytes) -> tuple[bool, str]:
    db = get_db()
    embedder = get_embedder()
    chunker = DocumentChunker(ocr_lang=OCR_LANG)
    md5 = md5_bytes(file_bytes)
    if db.is_indexed(md5):
        return False, f"'{filename}' ist bereits indexiert (Duplikat)."

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
        return True, f"'{filename}' indexiert - {added} Chunks."
    finally:
        tmp_path.unlink(missing_ok=True)


def _init_search_state():
    if "preview_open" not in st.session_state:
        st.session_state["preview_open"] = False
    if "preview_hit" not in st.session_state:
        st.session_state["preview_hit"] = None
    if "doc_download_open" not in st.session_state:
        st.session_state["doc_download_open"] = False
    if "doc_download_path" not in st.session_state:
        st.session_state["doc_download_path"] = ""
    if "doc_download_filename" not in st.session_state:
        st.session_state["doc_download_filename"] = ""

    if "search_state" in st.session_state:
        return
    st.session_state.search_state = {
        "request_id": 0,
        "query": "",
        "phase": "idle",
        "error": "",
        "status_text": STATUS_DESCRIPTIONS["idle"],
        "statusMessage": STATUS_DESCRIPTIONS["idle"],
        "progressSteps": [],
        "partialResults": [],
        "finalResult": {"hits": [], "answer": ""},
        "hits": [],
        "answer": "",
        "is_streaming": False,
        "cancel_requested": False,
        "started_at": None,
        "completed_at": None,
        "search_cache": {},
        "telemetry": {
            "first_hit_at": None,
            "first_token_at": None,
            "total_duration_ms": None,
            "cache_hit": False,
        },
    }


def _db_revision() -> int:
    return get_db().get_revision()


def _search_cache_key(question: str, llm_model: str, revision: int) -> tuple:
    return (question.strip().lower(), llm_model, int(MAX_RESULTS), int(revision))


def _search_cache_key_text(question: str, llm_model: str, revision: int) -> str:
    key = _search_cache_key(question, llm_model, revision)
    return str(key)


def _search_cache_get(question: str, llm_model: str, revision: int) -> dict | None:
    state = st.session_state.search_state
    cache = state.get("search_cache", {})
    key = _search_cache_key(question, llm_model, revision)
    item = cache.get(key)
    if item:
        age = time.time() - item.get("stored_at", 0.0)
        if age <= SEARCH_CACHE_TTL_SECONDS:
            item["cache_source"] = "session"
            return item
        cache.pop(key, None)
        state["search_cache"] = cache
        st.session_state.search_state = state

    try:
        persistent = get_persistent_search_cache().get(_search_cache_key_text(question, llm_model, revision))
    except Exception:
        persistent = None
    if persistent:
        persistent["cache_source"] = "persistent"
        cache[key] = {
            "hits": list(persistent.get("hits", [])),
            "answer": persistent.get("answer", ""),
            "stored_at": persistent.get("stored_at", time.time()),
        }
        state["search_cache"] = cache
        st.session_state.search_state = state
        return persistent
    return None


def _search_cache_put(question: str, llm_model: str, revision: int, hits: list[dict], answer: str):
    state = st.session_state.search_state
    cache = state.get("search_cache", {})
    key = _search_cache_key(question, llm_model, revision)
    cache[key] = {
        "hits": list(hits),
        "answer": answer,
        "stored_at": time.time(),
    }

    # bounded in-memory cache per session
    if len(cache) > 20:
        oldest = sorted(cache.items(), key=lambda item: item[1].get("stored_at", 0.0))[:5]
        for old_key, _ in oldest:
            cache.pop(old_key, None)

    state["search_cache"] = cache
    st.session_state.search_state = state
    try:
        get_persistent_search_cache().set(
            _search_cache_key_text(question, llm_model, revision),
            {
                "hits": list(hits),
                "answer": answer,
                "stored_at": cache[key]["stored_at"],
            },
        )
    except Exception:
        pass


def _build_progress_steps(current_phase: str) -> list[dict]:
    steps = [{"phase": p, "label": PHASE_LABELS[p], "state": "pending"} for p in SEARCH_PHASE_ORDER]
    if current_phase == "done":
        for step in steps:
            step["state"] = "done"
        return steps
    if current_phase == "error":
        return steps
    if current_phase == "idle":
        return steps
    if current_phase not in SEARCH_PHASE_ORDER:
        return steps

    active_idx = SEARCH_PHASE_ORDER.index(current_phase)
    for idx, step in enumerate(steps):
        if idx < active_idx:
            step["state"] = "done"
        elif idx == active_idx:
            step["state"] = "active"
    return steps


def _set_phase(phase: str, status_text: str = ""):
    state = st.session_state.search_state
    state["phase"] = normalize_transition(state.get("phase", "idle"), phase)
    if status_text:
        state["status_text"] = status_text
        state["statusMessage"] = status_text
    else:
        state["statusMessage"] = STATUS_DESCRIPTIONS.get(state["phase"], state.get("status_text", ""))
    state["progressSteps"] = _build_progress_steps(state["phase"])
    if phase == "started":
        state["started_at"] = time.time()
    if phase in TERMINAL_PHASES:
        state["completed_at"] = time.time()
    st.session_state.search_state = state


def _new_search(query: str):
    _close_preview()
    state = st.session_state.search_state
    state["request_id"] += 1
    state["query"] = query
    state["phase"] = "started"
    state["error"] = ""
    state["status_text"] = STATUS_DESCRIPTIONS["started"]
    state["statusMessage"] = STATUS_DESCRIPTIONS["started"]
    state["progressSteps"] = _build_progress_steps("started")
    state["partialResults"] = []
    state["finalResult"] = {"hits": [], "answer": ""}
    state["hits"] = []
    state["answer"] = ""
    state["is_streaming"] = False
    state["cancel_requested"] = False
    state["started_at"] = time.time()
    state["completed_at"] = None
    state["telemetry"] = {
        "first_hit_at": None,
        "first_token_at": None,
        "total_duration_ms": None,
        "cache_hit": False,
    }
    st.session_state.search_state = state


def _request_cancel():
    state = st.session_state.search_state
    state["cancel_requested"] = True
    state["is_streaming"] = False
    state["status_text"] = "Anfrage wurde abgebrochen."
    state["statusMessage"] = state["status_text"]
    state["phase"] = "error"
    state["error"] = state["status_text"]
    state["completed_at"] = time.time()
    state["progressSteps"] = _build_progress_steps("error")
    st.session_state.search_state = state


def _mark_first_hit():
    state = st.session_state.search_state
    telemetry = state.get("telemetry", {})
    if not telemetry.get("first_hit_at"):
        telemetry["first_hit_at"] = time.time()
        state["telemetry"] = telemetry
        st.session_state.search_state = state


def _mark_first_token():
    state = st.session_state.search_state
    telemetry = state.get("telemetry", {})
    if not telemetry.get("first_token_at"):
        telemetry["first_token_at"] = time.time()
        state["telemetry"] = telemetry
        st.session_state.search_state = state


def _finalize_telemetry():
    state = st.session_state.search_state
    started_at = state.get("started_at")
    now = time.time()
    telemetry = state.get("telemetry", {})
    if started_at:
        telemetry["total_duration_ms"] = int((now - started_at) * 1000)
    state["telemetry"] = telemetry
    st.session_state.search_state = state

    first_hit_ms = None
    first_token_ms = None
    if started_at and telemetry.get("first_hit_at"):
        first_hit_ms = int((telemetry["first_hit_at"] - started_at) * 1000)
    if started_at and telemetry.get("first_token_at"):
        first_token_ms = int((telemetry["first_token_at"] - started_at) * 1000)
    logger.info(
        "search telemetry phase=%s first_hit_ms=%s first_token_ms=%s total_duration_ms=%s cache_hit=%s",
        state.get("phase"),
        first_hit_ms,
        first_token_ms,
        telemetry.get("total_duration_ms"),
        telemetry.get("cache_hit", False),
    )


def _consume_stream_events(stream_builder, cancel_check):
    """Run streaming generator in a worker thread to improve cancellation behavior."""
    event_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    def _worker():
        try:
            # IMPORTANT: do not access Streamlit context from this worker thread.
            # Main thread updates stop_event when user/request cancellation is detected.
            generator = stream_builder(lambda: stop_event.is_set())
            for event in generator:
                event_queue.put(event)
                if event.get("type") in {"done", "error", "cancelled"}:
                    break
        except Exception as exc:
            event_queue.put({"type": "error", "content": str(exc)})
        finally:
            event_queue.put({"type": "__worker_done__"})

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    try:
        while True:
            if callable(cancel_check) and cancel_check():
                stop_event.set()
            try:
                event = event_queue.get(timeout=0.1)
            except queue.Empty:
                if not worker.is_alive():
                    break
                continue
            if event.get("type") == "__worker_done__":
                break
            yield event
            if event.get("type") in {"done", "error", "cancelled"}:
                break
    finally:
        stop_event.set()
        worker.join(timeout=1.5)


def _phase_chip_state(target_phase: str, current_phase: str) -> str:
    if current_phase == "error":
        return "status-chip problem"
    if current_phase == "idle":
        return "status-chip"
    if current_phase == "done":
        return "status-chip done"
    if current_phase in SEARCH_PHASE_ORDER:
        curr_idx = SEARCH_PHASE_ORDER.index(current_phase)
        tgt_idx = SEARCH_PHASE_ORDER.index(target_phase)
        if tgt_idx < curr_idx:
            return "status-chip done"
        if tgt_idx == curr_idx:
            return "status-chip active"
    return "status-chip"


def _render_status_panel():
    state = st.session_state.search_state
    phase = state["phase"]
    chips = []
    for key in SEARCH_PHASE_ORDER:
        cls = _phase_chip_state(key, phase)
        chips.append(f"<div class='{cls}'>{PHASE_LABELS[key]}</div>")

    details = state.get("statusMessage") or STATUS_DESCRIPTIONS.get(phase, state["status_text"])
    telemetry = state.get("telemetry", {})
    if telemetry.get("total_duration_ms"):
        details = f"{details} · Dauer {telemetry['total_duration_ms']} ms"
    if phase in {"retrieving", "reranking", "generating_answer"}:
        details = (
            f"{details} "
            "<span class='spark'></span><span class='spark'></span><span class='spark'></span>"
        )

    st.markdown(
        "<div class='glass-card'>"
        f"<div class='status-strip'>{''.join(chips)}</div>"
        f"<div class='meta-line'>{details}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    if phase in {"error"}:
        st.markdown(
            f"<div class='callout'>{PHASE_LABELS.get(phase, phase)}: {state['status_text']}</div>",
            unsafe_allow_html=True,
        )


def _render_results_panel(slot=None, interactive: bool = True):
    target = slot if slot is not None else st
    state = st.session_state.search_state
    hits = state["hits"]

    panel = target.container()
    panel.markdown("### Treffer")
    status_msg = state.get("statusMessage") or state.get("status_text") or STATUS_DESCRIPTIONS.get("idle")
    panel.caption(status_msg)
    progress_steps = state.get("progressSteps", [])
    if progress_steps:
        chips = []
        for step in progress_steps:
            css_cls = "status-chip"
            if step.get("state") == "active":
                css_cls = "status-chip active"
            elif step.get("state") == "done":
                css_cls = "status-chip done"
            elif state.get("phase") == "error":
                css_cls = "status-chip problem"
            chips.append(f"<div class='{css_cls}'>{html.escape(step.get('label', ''))}</div>")
        panel.markdown(
            "<div class='status-strip'>" + "".join(chips) + "</div>",
            unsafe_allow_html=True,
        )

    if state["phase"] in {"started", "retrieving", "reranking", "generating_answer"}:
        hit_count = len(state.get("partialResults", hits))
        panel.markdown(
            "<div class='live-row'>"
            f"<span>Live-Suche laeuft · {hit_count} Treffer sichtbar</span>"
            "<span class='spark'></span><span class='spark'></span><span class='spark'></span>"
            "</div>",
            unsafe_allow_html=True,
        )
    if state["phase"] in {"started", "retrieving", "reranking"} and not hits:
        panel.markdown(
            "<div class='glass-card'>"
            "<div class='skeleton line'></div>"
            "<div class='skeleton line short'></div>"
            "<div class='skeleton line'></div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    if not hits:
        panel.info("Noch keine Treffer sichtbar.")
        return

    if not interactive:
        rows = []
        for i, chunk in enumerate(hits, start=1):
            rel = chunk.get("relevance_score", 0)
            src = source_label(chunk.get("source_label", ""))
            title = f"{i}. {chunk.get('filename', '?')} (Seite {chunk.get('page', '?')})"
            snippet = (chunk.get("text", "") or "").replace("\n", " ").strip()[:220]
            title_esc = html.escape(title)
            src_esc = html.escape(src)
            snippet_esc = html.escape(snippet)
            rows.append(
                "<div class='hit-item'>"
                f"<div class='result-title'>{title_esc}</div>"
                f"<div class='result-sub'>{src_esc} · Relevanz {rel:.0%}</div>"
                f"<div class='result-snippet'>{snippet_esc}</div>"
                "</div>"
            )
        panel.markdown(
            "<div class='results-box'>"
            f"{''.join(rows)}"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    render_nonce = _next_render_nonce("hits_panel")
    with panel:
        for i, chunk in enumerate(hits, start=1):
            rel = chunk.get("relevance_score", 0.0)
            src = source_label(chunk.get("source_label", ""))
            snippet = (chunk.get("text", "") or "").replace("\n", " ").strip()[:220]
            page = int(chunk.get("page", 1) or 1)
            cidx = int(chunk.get("chunk_index", 0) or 0)
            key = _hit_widget_key(f"hit_preview_{render_nonce}", i, chunk)

            left, right = st.columns([7, 1.3], gap="small")
            with left:
                st.markdown(
                    "<div class='result-card'>"
                    f"<div class='result-title'>{html.escape(chunk.get('filename', '?'))}</div>"
                    f"<div class='result-sub'>Seite {page} · Chunk {cidx} · {html.escape(src)} · Relevanz {rel:.0%}</div>"
                    f"<div class='result-snippet'>{html.escape(snippet)}</div>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            with right:
                if st.button("Vorschau", key=key, use_container_width=True):
                    _open_preview_for_hit(chunk)
                    st.rerun()


def _render_answer_panel(slot=None):
    target = slot if slot is not None else st
    state = st.session_state.search_state
    target.markdown("### Antwort")
    answer = state["answer"]
    if state["phase"] == "error":
        msg = html.escape(state.get("error") or state.get("status_text") or "Unbekannter Fehler")
        target.markdown(f"<div class='answer-box'>Fehler: {msg}</div>", unsafe_allow_html=True)
        return
    show_pacman = state["phase"] in {"started", "retrieving", "reranking", "generating_answer"} or state["is_streaming"]
    if not answer and state["phase"] in {"started", "retrieving", "reranking", "generating_answer"}:
        status_msg = html.escape(state.get("statusMessage", "Antwort wird vorbereitet..."))
        target.markdown(
            "<div class='answer-box'>"
            "<div class='pacman-row'>"
            "<div class='pacman'>ᗧ</div>"
            "<span>Pac-Man sucht und spuckt gleich die Antwort aus...</span>"
            "<span class='pacman-dots'><span class='pacman-dot'></span><span class='pacman-dot'></span><span class='pacman-dot'></span></span>"
            "</div>"
            f"<div class='meta-line'>{status_msg}</div>"
            "<div class='skeleton line'></div>"
            "<div class='skeleton line short'></div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    if not answer:
        target.markdown("<div class='answer-box'>Noch keine Antwort vorhanden.</div>", unsafe_allow_html=True)
        return

    safe_answer = html.escape(answer).replace("\n", "<br>")
    if show_pacman:
        target.markdown(
            "<div class='answer-box answer-streaming'>"
            "<div class='pacman-row'>"
            "<div class='pacman'>ᗧ</div>"
            "<span>Pac-Man spuckt die Antwort langsam aus</span>"
            "<span class='pacman-dots'><span class='pacman-dot'></span><span class='pacman-dot'></span><span class='pacman-dot'></span></span>"
            "</div>"
            f"{safe_answer}"
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        target.markdown(f"<div class='answer-box'>{safe_answer}</div>", unsafe_allow_html=True)


def _run_search_pipeline(question: str, results_slot=None, answer_slot=None):
    db = get_db()
    embedder = get_embedder()
    active_llm = st.session_state.get("llm_model", OLLAMA_LLM_MODEL)
    rag = get_rag(active_llm)
    search_service = SearchService(
        db=db,
        embedder=embedder,
        rag=rag,
        max_results=MAX_RESULTS,
    )

    state = st.session_state.search_state
    request_id = state["request_id"]
    revision = _db_revision()

    cached = _search_cache_get(question, active_llm, revision)
    if cached:
        age = int(time.time() - cached.get("stored_at", time.time()))
        state = st.session_state.search_state
        cached_hits = list(cached.get("hits", []))
        cached_answer = cached.get("answer", "")
        state["hits"] = cached_hits
        state["partialResults"] = cached_hits
        state["answer"] = cached_answer
        state["finalResult"] = {"hits": cached_hits, "answer": cached_answer}
        state["status_text"] = f"Antwort aus Cache ({age}s alt)."
        state["statusMessage"] = state["status_text"]
        state["is_streaming"] = False
        telemetry = state.get("telemetry", {})
        telemetry["cache_hit"] = True
        telemetry["total_duration_ms"] = int((time.time() - state.get("started_at", time.time())) * 1000)
        state["telemetry"] = telemetry
        st.session_state.search_state = state
        _set_phase("done", state["status_text"])
        _finalize_telemetry()
        return

    _set_phase("started", STATUS_DESCRIPTIONS["started"])
    _render_results_panel(results_slot, interactive=False)
    _render_answer_panel(answer_slot)

    try:
        def _cancelled() -> bool:
            current = st.session_state.search_state
            return current.get("cancel_requested", False) or current.get("request_id") != request_id

        if not USE_SEARCH_STREAMING:
            result = search_service.search(question, cancel_check=_cancelled)
            state = st.session_state.search_state
            state["hits"] = list(result.get("hits", []))
            state["partialResults"] = list(result.get("hits", []))
            state["answer"] = result.get("answer", "")
            state["finalResult"] = {"hits": list(result.get("hits", [])), "answer": state["answer"]}
            state["status_text"] = result.get("statusMessage", "Suche abgeschlossen.")
            state["statusMessage"] = state["status_text"]
            state["is_streaming"] = False
            st.session_state.search_state = state
            _set_phase("done", state["status_text"])
            _search_cache_put(
                question=question,
                llm_model=active_llm,
                revision=revision,
                hits=state["hits"],
                answer=state["answer"],
            )
            return

        stream_failed = None
        done_received = False

        for event in search_service.search_stream(question, cancel_check=_cancelled):
            if st.session_state.search_state["request_id"] != request_id:
                return
            if st.session_state.search_state.get("cancel_requested"):
                raise RuntimeError("Anfrage wurde abgebrochen.")

            event_type = event.get("type")
            state = st.session_state.search_state

            if event_type == "started":
                _set_phase("started", event.get("statusMessage", STATUS_DESCRIPTIONS["started"]))
            elif event_type == "retrieving":
                _set_phase("retrieving", event.get("statusMessage", STATUS_DESCRIPTIONS["retrieving"]))
            elif event_type == "reranking":
                _set_phase("reranking", event.get("statusMessage", STATUS_DESCRIPTIONS["reranking"]))
            elif event_type == "partial_results":
                partial = list(event.get("partialResults", []))
                state["partialResults"] = partial
                state["hits"] = partial
                state["status_text"] = event.get("statusMessage", f"{len(partial)} Treffer sichtbar.")
                state["statusMessage"] = state["status_text"]
                st.session_state.search_state = state
                if partial:
                    _mark_first_hit()
                # Keep current active retrieval/reranking phase, default to retrieving.
                if st.session_state.search_state.get("phase") not in {"reranking"}:
                    _set_phase("retrieving", state["status_text"])
            elif event_type == "generating_answer":
                answer_text = event.get("answer", state.get("answer", ""))
                if event.get("answerDelta"):
                    _mark_first_token()
                state["is_streaming"] = True
                state["answer"] = answer_text
                state["status_text"] = event.get("statusMessage", STATUS_DESCRIPTIONS["generating_answer"])
                state["statusMessage"] = state["status_text"]
                state["finalResult"] = {
                    "hits": list(state.get("hits", [])),
                    "answer": answer_text,
                }
                st.session_state.search_state = state
                _set_phase("generating_answer", state["status_text"])
            elif event_type == "done":
                done_received = True
                final_hits = list(event.get("hits", state.get("hits", [])))
                final_answer = event.get("answer", state.get("answer", ""))
                status_msg = event.get("statusMessage", STATUS_DESCRIPTIONS["done"])
                state["hits"] = final_hits
                state["partialResults"] = final_hits
                state["answer"] = final_answer
                state["finalResult"] = {"hits": final_hits, "answer": final_answer}
                state["status_text"] = status_msg
                state["statusMessage"] = status_msg
                state["is_streaming"] = False
                st.session_state.search_state = state
                _set_phase("done", status_msg)
                _search_cache_put(
                    question=question,
                    llm_model=active_llm,
                    revision=revision,
                    hits=final_hits,
                    answer=final_answer,
                )
                _render_results_panel(results_slot, interactive=False)
                _render_answer_panel(answer_slot)
                break
            elif event_type == "error":
                stream_failed = RuntimeError(event.get("message", "Unbekannter Streaming-Fehler"))
                raise stream_failed

            _render_results_panel(results_slot, interactive=False)
            _render_answer_panel(answer_slot)

        if not done_received and stream_failed is None:
            stream_failed = RuntimeError("Streaming-Ende ohne done-Event.")
            raise stream_failed

    except RuntimeError as exc:
        # Fallback for environments where streaming path is not available.
        if "Streaming-Ende ohne done-Event" in str(exc):
            result = search_service.search(question, cancel_check=lambda: False)
            state = st.session_state.search_state
            state["hits"] = list(result.get("hits", []))
            state["partialResults"] = list(result.get("hits", []))
            state["answer"] = result.get("answer", "")
            state["finalResult"] = {"hits": list(result.get("hits", [])), "answer": state["answer"]}
            state["status_text"] = result.get("statusMessage", "Fallback-Suche abgeschlossen.")
            state["statusMessage"] = state["status_text"]
            state["is_streaming"] = False
            st.session_state.search_state = state
            _set_phase("done", state["status_text"])
            _search_cache_put(
                question=question,
                llm_model=active_llm,
                revision=revision,
                hits=state["hits"],
                answer=state["answer"],
            )
        else:
            state = st.session_state.search_state
            state["error"] = str(exc)
            state["status_text"] = str(exc)
            state["statusMessage"] = str(exc)
            st.session_state.search_state = state
            _set_phase("error", str(exc))
    except Exception as exc:
        state = st.session_state.search_state
        state["error"] = str(exc)
        state["status_text"] = str(exc)
        state["statusMessage"] = str(exc)
        st.session_state.search_state = state
        _set_phase("error", str(exc))
    finally:
        # Avoid hanging loader state after any failure path.
        state = st.session_state.search_state
        state["is_streaming"] = False
        st.session_state.search_state = state
        _finalize_telemetry()


def tab_suche():
    st.header("Dokumentensuche")
    _init_search_state()

    stats = get_db_stats_cached()
    if stats["total_documents"] == 0:
        st.info("Noch keine Dokumente indexiert. Paperless-Archiv und Inbox werden automatisch ueberwacht.")
        return

    st.caption(f"{stats['total_documents']} Dokumente · {stats['total_chunks']} Chunks indexiert")

    left, center, right = st.columns([6, 1.2, 1.2])
    with left:
        query = st.text_input(
            "Frage stellen",
            placeholder="z.B. Welche Rechnungen gibt es von 2024?",
            key="search_q",
            label_visibility="collapsed",
        )
    with center:
        run_search = st.button("Suchen", type="primary", use_container_width=True)
    with right:
        cancel_search = st.button("Abbrechen", use_container_width=True)

    llm_col, llm_status_col = st.columns([3, 3])
    with llm_col:
        selected_llm, llm_online = _render_llm_selector(prefix="search")
    with llm_status_col:
        if llm_online:
            st.success("LLM online und auswählbar")
        else:
            st.warning("LLM derzeit nicht online")

    if cancel_search:
        _request_cancel()

    if run_search and query.strip():
        _new_search(query.strip())
        st.session_state["_do_search"] = True
    elif run_search and not query.strip():
        st.warning("Bitte eine Suchfrage eingeben.")

    results_slot = st.empty()
    answer_slot = st.empty()
    run_now = st.session_state.pop("_do_search", False)
    if run_now:
        _render_results_panel(results_slot, interactive=False)
        _render_answer_panel(answer_slot)
        _run_search_pipeline(
            st.session_state.search_state["query"],
            results_slot=results_slot,
            answer_slot=answer_slot,
        )
        _render_results_panel(results_slot)
        _render_answer_panel(answer_slot)
        _maybe_open_preview_dialog()
    else:
        _render_results_panel(results_slot)
        _render_answer_panel(answer_slot)
        _maybe_open_preview_dialog()


def tab_hochladen():
    st.header("Dokument hochladen & indexieren")
    st.info(
        f"Automatisch ueberwacht:\n"
        f"- Paperless-Archiv: `{PAPERLESS_ARCHIVE}`\n"
        f"- Inbox: `{INBOX_FOLDER}`\n\n"
        "Oder hier direkt hochladen:"
    )

    ext_list = ", ".join(sorted(SUPPORTED_EXTENSIONS))
    st.caption(f"Unterstuetzte Formate: {ext_list}")

    uploaded_files = st.file_uploader(
        "Dateien auswaehlen",
        type=[e.lstrip(".") for e in SUPPORTED_EXTENSIONS],
        accept_multiple_files=True,
        key="uploader",
    )

    if uploaded_files and st.button("Alle indexieren", type="primary"):
        for uf in uploaded_files:
            file_bytes = uf.read()
            with st.status(f"Verarbeite '{uf.name}'...", expanded=True) as status:
                st.write("Chunking + OCR...")
                success, msg = _index_file_bytes(uf.name, file_bytes)
                if success:
                    invalidate_ui_caches()
                    status.update(label=f"'{uf.name}' - fertig", state="complete")
                    st.success(msg)
                else:
                    status.update(label=f"'{uf.name}' - uebersprungen", state="error")
                    st.warning(msg)


def tab_dokumente():
    st.header("Indexierte Dokumente")

    db = get_db()
    docs = list_documents_cached()
    if not docs:
        st.info("Keine Dokumente indexiert.")
        return

    by_source: dict[str, list] = {}
    for doc in docs:
        lbl = doc.get("source_label", "unbekannt")
        by_source.setdefault(lbl, []).append(doc)

    st.caption(f"{len(docs)} Dokumente insgesamt")

    for lbl, group in by_source.items():
        with st.expander(f"{source_label(lbl)} ({len(group)} Dokumente)", expanded=True):
            for doc in group:
                c1, c2, c3 = st.columns([5, 2, 1])
                with c1:
                    st.text(f"{doc['filename']} ({doc['chunk_count']} Chunks)")
                with c2:
                    file_path = Path(doc.get("source", ""))
                    if not file_path.exists():
                        alt_path = Path(UPLOAD_FOLDER) / doc["filename"]
                        if alt_path.exists():
                            file_path = alt_path
                    if file_path.exists():
                        if st.button("Download", key=f"dl_open_{lbl}_{doc['filename']}"):
                            _open_doc_download(str(file_path), doc["filename"])
                            st.rerun()
                    else:
                        st.caption("Datei nicht lokal")
                with c3:
                    if st.button("Loeschen", key=f"del_{lbl}_{doc['filename']}"):
                        deleted = db.delete_document(doc["filename"])
                        invalidate_ui_caches()
                        st.success(f"{doc['filename']} geloescht ({deleted} Chunks).")
                        st.rerun()


def tab_status():
    st.header("System-Status")

    embedder = get_embedder()
    db = get_db()

    st.subheader("Ollama")
    ok, msg = embedder.check_connection()
    if ok:
        st.success(f"Verbunden: {OLLAMA_URL}")
        st.caption(msg)
    else:
        st.error(f"Nicht erreichbar: {OLLAMA_URL}")
        st.caption(msg)

    _, llm_online = _render_llm_selector(prefix="status")
    if llm_online:
        st.success("Ausgewähltes Modell ist verfügbar.")
    else:
        st.warning("Ausgewähltes Modell ist derzeit nicht verfügbar.")

    st.divider()
    st.subheader("Watch-Ordner")
    for watcher in _multi_watcher.watchers:
        status = "aktiv" if watcher.is_running else "inaktiv"
        icon = SOURCE_ICONS.get(watcher._source_label, watcher._source_label)
        st.text(f"{status}: {icon}: {watcher._watch_folder}")

    st.divider()
    st.subheader("Indexierung")
    c1, c2 = st.columns([2, 3])
    with c1:
        if st.button("Neu indexieren", type="primary", use_container_width=True):
            _multi_watcher.reindex()
            invalidate_ui_caches()
            st.success("Gestartet - neue Dokumente erscheinen nach Verarbeitung.")
    with c2:
        st.caption("Nuetzlich nach Aenderungen an Ordnern oder Modellen.")

    st.divider()
    st.subheader("Datenbank (ChromaDB)")
    stats = get_db_stats_cached()
    m1, m2, m3 = st.columns(3)
    m1.metric("Dokumente", stats["total_documents"])
    m2.metric("Chunks", stats["total_chunks"])
    m3.metric("Speicher", f"{stats['db_size_mb']} MB")

    if "confirm_reset" not in st.session_state:
        st.session_state.confirm_reset = False

    if not st.session_state.confirm_reset:
        if st.button("Datenbank leeren"):
            st.session_state.confirm_reset = True
            st.rerun()
    else:
        st.warning(f"Alle {stats['total_documents']} Dokumente werden geloescht.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Ja, alles loeschen", type="primary", use_container_width=True):
                deleted = db.reset()
                st.cache_resource.clear()
                invalidate_ui_caches()
                st.session_state.confirm_reset = False
                st.success(f"Datenbank geleert - {deleted} Chunks geloescht.")
                st.rerun()
        with c2:
            if st.button("Abbrechen", use_container_width=True):
                st.session_state.confirm_reset = False
                st.rerun()

    st.divider()
    st.subheader("Konfiguration")
    config_data = {
        "Ollama URL": OLLAMA_URL,
        "Embedding-Modell": OLLAMA_EMBED_MODEL,
        "LLM-Modell": OLLAMA_LLM_MODEL,
        "LLM-Modus": "Claude API" if USE_CLAUDE else f"Ollama ({OLLAMA_LLM_MODEL})",
        "Paperless-Archiv": PAPERLESS_ARCHIVE,
        "Inbox-Ordner": INBOX_FOLDER,
        "OCR-Sprachen": OCR_LANG,
        "Max. Ergebnisse": str(MAX_RESULTS),
        "ChromaDB-Pfad": CHROMADB_PATH,
    }
    for key, val in config_data.items():
        c1, c2 = st.columns([2, 3])
        c1.caption(key)
        c2.text(val)


st.title("Dokumentensuche")
tab1, tab2, tab3, tab4 = st.tabs(["Suche", "Hochladen", "Dokumente", "Status"])

with tab1:
    tab_suche()
with tab2:
    tab_hochladen()
with tab3:
    tab_dokumente()
    _maybe_open_doc_download_dialog()
with tab4:
    tab_status()

