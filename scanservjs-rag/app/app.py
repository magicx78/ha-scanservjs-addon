"""
scanservjs-rag - local document search with progressive RAG UX.
"""

import hashlib
import html
import logging
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from lib.chunker import DocumentChunker, SUPPORTED_EXTENSIONS
from lib.embedder import OllamaEmbedder
from lib.rag import RAGEngine
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

SEARCH_PHASE_ORDER = [
    "started",
    "finding_hits",
    "building_answer",
    "expanding_result",
    "completed",
]
TERMINAL_PHASES = {"completed", "empty", "error", "cancelled"}

SOURCE_ICONS = {
    "paperless": "Paperless",
    "inbox": "Inbox",
    "upload": "Upload",
}

PHASE_LABELS = {
    "started": "Suche gestartet",
    "finding_hits": "Treffer werden gefunden",
    "building_answer": "Verarbeitung / Antwortaufbau laeuft",
    "expanding_result": "Ergebnis wird erweitert",
    "completed": "Abgeschlossen",
    "empty": "Leerzustand",
    "error": "Fehler",
    "cancelled": "Abgebrochen",
}

STATUS_DESCRIPTIONS = {
    "started": "Anfrage initialisiert und Suchlauf vorbereitet.",
    "finding_hits": "Erste relevante Quellen werden semantisch ermittelt.",
    "building_answer": "Antwort wird live aus den ersten Treffern aufgebaut.",
    "expanding_result": "Antwort wird mit weiteren Treffern erweitert.",
    "completed": "Suchlauf ist abgeschlossen.",
    "empty": "Es wurden keine relevanten Treffer gefunden.",
    "error": "Die Verarbeitung wurde mit Fehler beendet.",
    "cancelled": "Anfrage wurde manuell abgebrochen.",
}

DESIGN_CSS = """
<style>
:root {
  --bg: #f5f8fb;
  --surface: #ffffff;
  --surface-strong: #f0f5ff;
  --text: #10233d;
  --muted: #5a6e89;
  --line: #d8e2f0;
  --accent: #1366d6;
  --ok: #0f8b53;
  --warn: #b6650a;
  --err: #c93d2f;
  --radius: 14px;
  --radius-sm: 10px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0c1420;
    --surface: #121d2b;
    --surface-strong: #18283b;
    --text: #e7eef7;
    --muted: #9db0c9;
    --line: #2b3b50;
    --accent: #62a3ff;
    --ok: #47ca88;
    --warn: #f2b458;
    --err: #ff8174;
  }
}
.stApp {
  background: radial-gradient(circle at 5% 0%, rgba(19,102,214,0.06), transparent 28%), var(--bg);
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

    if INBOX_FOLDER and INBOX_FOLDER != "null":
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

    multi = MultiWatcher(watchers)
    multi.index_all_existing()
    multi.start_all()
    return multi


_multi_watcher = get_multi_watcher()


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def source_label(label: str) -> str:
    return SOURCE_ICONS.get(label, f"Quelle: {label}")


def _render_llm_selector(prefix: str = "search"):
    embedder = get_embedder()
    models = embedder.list_models()
    current_llm = st.session_state.get("llm_model", OLLAMA_LLM_MODEL)

    if not models:
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
    if "search_state" in st.session_state:
        return
    st.session_state.search_state = {
        "request_id": 0,
        "query": "",
        "phase": "completed",
        "error": "",
        "status_text": "Bereit",
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


def _set_phase(phase: str, status_text: str = ""):
    state = st.session_state.search_state
    state["phase"] = normalize_transition(state.get("phase", "completed"), phase)
    if status_text:
        state["status_text"] = status_text
    if phase == "started":
        state["started_at"] = time.time()
    if phase in TERMINAL_PHASES:
        state["completed_at"] = time.time()
    st.session_state.search_state = state


def _new_search(query: str):
    state = st.session_state.search_state
    state["request_id"] += 1
    state["query"] = query
    state["phase"] = "started"
    state["error"] = ""
    state["status_text"] = STATUS_DESCRIPTIONS["started"]
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
    state["status_text"] = STATUS_DESCRIPTIONS["cancelled"]
    state["phase"] = "cancelled"
    state["completed_at"] = time.time()
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
            generator = stream_builder(
                lambda: stop_event.is_set() or (callable(cancel_check) and cancel_check())
            )
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
    if current_phase in {"error", "empty", "cancelled"}:
        if target_phase == "completed":
            return "status-chip problem"
        if target_phase in SEARCH_PHASE_ORDER and SEARCH_PHASE_ORDER.index(target_phase) < 2:
            return "status-chip done"
        return "status-chip"
    if current_phase not in SEARCH_PHASE_ORDER:
        return "status-chip"

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

    details = STATUS_DESCRIPTIONS.get(phase, state["status_text"])
    if state["status_text"] and state["status_text"] != details:
        details = f"{details} {state['status_text']}"
    telemetry = state.get("telemetry", {})
    if telemetry.get("total_duration_ms"):
        details = f"{details} · Dauer {telemetry['total_duration_ms']} ms"
    if phase in {"finding_hits", "building_answer", "expanding_result"}:
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
    if phase in {"error", "empty", "cancelled"}:
        st.markdown(
            f"<div class='callout'>{PHASE_LABELS[phase]}: {state['status_text']}</div>",
            unsafe_allow_html=True,
        )


def _render_results_panel():
    state = st.session_state.search_state
    hits = state["hits"]
    st.markdown("### Treffer")
    if state["phase"] in {"started", "finding_hits"} and not hits:
        st.markdown(
            "<div class='glass-card'>"
            "<div class='skeleton line'></div>"
            "<div class='skeleton line short'></div>"
            "<div class='skeleton line'></div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    if not hits:
        st.info("Noch keine Treffer sichtbar.")
        return

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
    st.markdown(
        "<div class='results-box'>"
        f"{''.join(rows)}"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_answer_panel():
    state = st.session_state.search_state
    st.markdown("### Antwort")
    answer = state["answer"]
    if not answer and state["phase"] in {"started", "finding_hits", "building_answer"}:
        st.markdown(
            "<div class='answer-box'>"
            "<div class='skeleton line'></div>"
            "<div class='skeleton line'></div>"
            "<div class='skeleton line short'></div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    if not answer:
        st.markdown("<div class='answer-box'>Noch keine Antwort vorhanden.</div>", unsafe_allow_html=True)
        return

    css_class = "answer-box answer-streaming" if state["is_streaming"] else "answer-box"
    safe_answer = html.escape(answer).replace("\n", "<br>")
    st.markdown(f"<div class='{css_class}'>{safe_answer}</div>", unsafe_allow_html=True)


def _run_search_pipeline(question: str):
    db = get_db()
    embedder = get_embedder()
    active_llm = st.session_state.get("llm_model", OLLAMA_LLM_MODEL)
    rag = get_rag(active_llm)

    state = st.session_state.search_state
    request_id = state["request_id"]
    revision = _db_revision()

    cached = _search_cache_get(question, active_llm, revision)
    if cached:
        age = int(time.time() - cached.get("stored_at", time.time()))
        state = st.session_state.search_state
        state["hits"] = list(cached.get("hits", []))
        state["answer"] = cached.get("answer", "")
        state["status_text"] = f"Antwort aus Cache ({age}s alt)."
        state["is_streaming"] = False
        telemetry = state.get("telemetry", {})
        telemetry["cache_hit"] = True
        telemetry["total_duration_ms"] = int((time.time() - state.get("started_at", time.time())) * 1000)
        state["telemetry"] = telemetry
        st.session_state.search_state = state
        _set_phase("completed", state["status_text"])
        _finalize_telemetry()
        return

    _set_phase("started", STATUS_DESCRIPTIONS["started"])
    _render_status_panel()
    _render_results_panel()
    _render_answer_panel()

    try:
        def _cancelled() -> bool:
            current = st.session_state.search_state
            return current.get("cancel_requested", False) or current.get("request_id") != request_id

        query_embedding = embedder.embed(question)
        if not query_embedding:
            raise RuntimeError("Embedding fehlgeschlagen. Ist Ollama erreichbar?")

        steps = sorted({1, max(1, MAX_RESULTS)})
        prog = db.search_progressive(query_embedding=query_embedding, steps=steps)

        first_context = []
        for payload in prog:
            if st.session_state.search_state["request_id"] != request_id:
                return
            if st.session_state.search_state["cancel_requested"]:
                _set_phase("cancelled", STATUS_DESCRIPTIONS["cancelled"])
                return

            state = st.session_state.search_state
            state["hits"] = payload["results"]
            if payload.get("error"):
                state["status_text"] = f"Teilweise Suche mit Warnung: {payload['error'][:120]}"
            else:
                state["status_text"] = (
                    f"{len(payload['results'])} Treffer sichtbar (Stufe {payload['step']}/{len(steps)})."
                )
            st.session_state.search_state = state
            _set_phase("finding_hits", state["status_text"])
            _render_status_panel()
            _render_results_panel()
            _render_answer_panel()

            if payload["results"]:
                _mark_first_hit()
                first_context = list(payload["results"])
                break
            time.sleep(0.01)

        if not first_context:
            _set_phase("empty", STATUS_DESCRIPTIONS["empty"])
            return

        state = st.session_state.search_state
        state["is_streaming"] = True
        state["status_text"] = STATUS_DESCRIPTIONS["building_answer"]
        st.session_state.search_state = state
        _set_phase("building_answer", STATUS_DESCRIPTIONS["building_answer"])

        answer_text = ""
        for event in _consume_stream_events(
            lambda cancel_cb: rag.answer_stream(
                question,
                first_context,
                mode="initial",
                cancel_check=cancel_cb,
            ),
            cancel_check=_cancelled,
        ):
            if st.session_state.search_state["request_id"] != request_id:
                return
            if st.session_state.search_state["cancel_requested"]:
                _set_phase("cancelled", STATUS_DESCRIPTIONS["cancelled"])
                return
            if event["type"] == "token":
                _mark_first_token()
                answer_text += event["content"]
                state = st.session_state.search_state
                state["answer"] = answer_text
                st.session_state.search_state = state
                _render_status_panel()
                _render_results_panel()
                _render_answer_panel()
            elif event["type"] == "meta":
                state = st.session_state.search_state
                state["status_text"] = event["content"]
                st.session_state.search_state = state
                _render_status_panel()
            elif event["type"] == "error":
                raise RuntimeError(event["content"])
            elif event["type"] == "cancelled":
                _set_phase("cancelled", STATUS_DESCRIPTIONS["cancelled"])
                return
            elif event["type"] == "done":
                answer_text = event.get("content", answer_text)

        state = st.session_state.search_state
        state["is_streaming"] = False
        state["answer"] = answer_text or "Keine Antwort erhalten."
        st.session_state.search_state = state

        expanded = False
        for payload in prog:
            if st.session_state.search_state["request_id"] != request_id:
                return
            if st.session_state.search_state["cancel_requested"]:
                _set_phase("cancelled", STATUS_DESCRIPTIONS["cancelled"])
                return

            if payload["new_results"]:
                expanded = True
            state = st.session_state.search_state
            state["hits"] = payload["results"]
            state["status_text"] = (
                f"Erweitert auf {len(payload['results'])} Treffer (Stufe {payload['step']}/{len(steps)})."
            )
            st.session_state.search_state = state
            _set_phase("expanding_result", state["status_text"])
            _render_status_panel()
            _render_results_panel()
            _render_answer_panel()
            time.sleep(0.01)

        if ENABLE_REFINE and expanded and st.session_state.search_state["hits"]:
            state = st.session_state.search_state
            state["is_streaming"] = True
            state["status_text"] = STATUS_DESCRIPTIONS["expanding_result"]
            st.session_state.search_state = state
            _set_phase("expanding_result", STATUS_DESCRIPTIONS["expanding_result"])
            refined_answer = ""
            for event in _consume_stream_events(
                lambda cancel_cb: rag.answer_stream(
                    question,
                    st.session_state.search_state["hits"],
                    mode="refine",
                    current_answer=st.session_state.search_state["answer"],
                    cancel_check=cancel_cb,
                ),
                cancel_check=_cancelled,
            ):
                if st.session_state.search_state["request_id"] != request_id:
                    return
                if st.session_state.search_state["cancel_requested"]:
                    _set_phase("cancelled", STATUS_DESCRIPTIONS["cancelled"])
                    return
                if event["type"] == "token":
                    refined_answer += event["content"]
                    state = st.session_state.search_state
                    state["answer"] = refined_answer
                    st.session_state.search_state = state
                    _render_status_panel()
                    _render_results_panel()
                    _render_answer_panel()
                elif event["type"] == "meta":
                    state = st.session_state.search_state
                    state["status_text"] = event["content"]
                    st.session_state.search_state = state
                    _render_status_panel()
                elif event["type"] == "error":
                    raise RuntimeError(event["content"])
                elif event["type"] == "cancelled":
                    _set_phase("cancelled", STATUS_DESCRIPTIONS["cancelled"])
                    return
                elif event["type"] == "done":
                    refined_answer = event.get("content", refined_answer)
            state = st.session_state.search_state
            state["answer"] = refined_answer or state["answer"]
            state["is_streaming"] = False
            st.session_state.search_state = state

        _search_cache_put(
            question=question,
            llm_model=active_llm,
            revision=revision,
            hits=st.session_state.search_state["hits"],
            answer=st.session_state.search_state["answer"],
        )
        _set_phase("completed", STATUS_DESCRIPTIONS["completed"])
    except Exception as exc:
        state = st.session_state.search_state
        state["error"] = str(exc)
        state["status_text"] = str(exc)
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

    _render_status_panel()
    _render_results_panel()
    _render_answer_panel()

    if st.session_state.pop("_do_search", False):
        _run_search_pipeline(st.session_state.search_state["query"])
        _render_status_panel()
        _render_results_panel()
        _render_answer_panel()


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
                        with open(file_path, "rb") as f:
                            st.download_button(
                                label="Download",
                                data=f.read(),
                                file_name=doc["filename"],
                                key=f"dl_{lbl}_{doc['filename']}",
                            )
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
with tab4:
    tab_status()

