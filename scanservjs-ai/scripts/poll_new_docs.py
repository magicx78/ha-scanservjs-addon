#!/usr/bin/env python3
"""
Pollt Paperless-ngx auf neue unkategorisierte Dokumente
und ruft auto_consume.py fuer jedes auf.

Cron: */5 * * * * python3 /config/scripts/poll_new_docs.py
"""

import fcntl
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests
import yaml

SCRIPT_DIR = Path(__file__).parent
LOCK_FILE = SCRIPT_DIR / "poll_new_docs.lock"

# Default-Konfiguration für Retry-Logik
DEFAULT_MAX_RETRIES = 3
DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_BACKOFF_FACTOR = 2  # exponential: 15s → 30s → 60s

_ENV_OVERRIDES = {
    "paperless_url":   "PAPERLESS_URL",
    "paperless_token": "PAPERLESS_TOKEN",
}


def load_config() -> dict:
    try:
        with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        cfg = {}
    for key, env_var in _ENV_OVERRIDES.items():
        val = os.environ.get(env_var)
        if val:
            cfg[key] = val
    return cfg


def setup_logging() -> logging.Logger:
    """Setup für poll_new_docs Logging."""
    logger = logging.getLogger("poll_new_docs")
    logger.setLevel(logging.DEBUG)

    # Nur stderr (für Cron-Ausgabe)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)

    return logger


def print_preview(docs: list, session: requests.Session, base: str) -> None:
    """Zeigt eine uebersichtliche Liste aller verarbeiteten Dokumente."""
    print("\n" + "=" * 70)
    print(f"  PAPERLESS-AI  –  {len(docs)} Dokument(e) zur Verarbeitung")
    print("=" * 70)
    for doc in docs:
        doc_id = doc["id"]
        title = doc.get("title") or f"doc_{doc_id}"
        added = (doc.get("added") or "")[:10]

        # Tags nachladen
        tag_ids = doc.get("tags") or []
        tag_names: list[str] = []
        if tag_ids:
            try:
                t = session.get(f"{base}/api/tags/", params={"id__in": ",".join(str(i) for i in tag_ids)}, timeout=10)
                tag_names = [r["name"] for r in t.json().get("results", [])]
            except Exception:
                tag_names = [str(i) for i in tag_ids]

        tag_str = "  ".join(f"[{n}]" for n in tag_names) if tag_names else "(keine Tags)"
        print(f"\n  ID {doc_id:>4}  |  {added}  |  {title[:50]}")
        print(f"           Tags: {tag_str}")
    print("\n" + "=" * 70 + "\n")


def main() -> None:
    # Process-Lock verhindert parallele Cron-Laeufe
    lock_fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("poll_new_docs.py laeuft bereits – Abbruch.", file=sys.stderr)
        lock_fh.close()
        return

    try:
        _run()
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def _get_ki_tag_id(session: requests.Session, base: str, logger: logging.Logger) -> Optional[int]:
    """Gibt die ID des Tags 'KI-Verarbeitet' zurück (None falls nicht vorhanden)."""
    try:
        resp = session.get(
            f"{base}/api/tags/",
            params={"name__iexact": "KI-Verarbeitet"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        return int(results[0]["id"]) if results else None
    except requests.RequestException as exc:
        logger.warning(f"Fehler beim Abrufen des KI-Verarbeitet-Tags: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Unerwarteter Fehler beim Tag-Abruf: {exc}")
        return None


def _api_request_with_retry(
    session: requests.Session, url: str, max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: int = DEFAULT_REQUEST_TIMEOUT, logger: Optional[logging.Logger] = None, **kwargs
) -> Optional[requests.Response]:
    """Führt HTTP-Request mit Retry-Logik durch.

    Args:
        session: requests.Session
        url: API-URL
        max_retries: Maximal Anzahl Versuche
        timeout: Request-Timeout in Sekunden
        logger: Logging-Instanz (optional)
        **kwargs: Zusätzliche Session.get() Parameter

    Returns:
        Response-Objekt oder None bei schwerem Fehler
    """
    backoff_factor = DEFAULT_BACKOFF_FACTOR
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if logger:
                logger.warning(f"Timeout (Versuch {attempt}/{max_retries}): {exc}")
            if attempt < max_retries:
                wait_time = timeout * (backoff_factor ** (attempt - 1))
                time.sleep(min(wait_time, 120))  # Max 2 Minuten
        except requests.exceptions.ConnectionError as exc:
            last_exc = exc
            if logger:
                logger.warning(f"Verbindungsfehler (Versuch {attempt}/{max_retries}): {exc}")
            if attempt < max_retries:
                wait_time = timeout * (backoff_factor ** (attempt - 1))
                time.sleep(min(wait_time, 120))
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            if exc.response.status_code in (401, 403):
                if logger:
                    logger.error(f"Authentifizierungsfehler ({exc.response.status_code}) – nicht wiederholbar")
                return None  # Nicht wiederholen
            elif exc.response.status_code >= 500:
                if logger:
                    logger.warning(f"Server-Fehler (Versuch {attempt}/{max_retries}): {exc}")
                if attempt < max_retries:
                    wait_time = timeout * (backoff_factor ** (attempt - 1))
                    time.sleep(min(wait_time, 120))
            else:
                if logger:
                    logger.error(f"HTTP-Fehler ({exc.response.status_code}): {exc}")
                return None
        except requests.RequestException as exc:
            last_exc = exc
            if logger:
                logger.error(f"Request-Fehler: {exc}")
            return None

    # Zu viele Fehlversuche
    if logger:
        logger.error(f"Zu viele Fehler nach {max_retries} Versuchen – gebe auf")
    return None


def _run() -> None:
    logger = setup_logging()
    config = load_config()
    base = (config.get("paperless_url") or "").rstrip("/")
    token = config.get("paperless_token") or ""

    if not base or not token:
        logger.error("[poll] paperless_url oder paperless_token fehlt in config.yaml – Abbruch")
        return

    session = requests.Session()
    session.headers["Authorization"] = f"Token {token}"

    # Konfiguration laden
    max_retries = int(config.get("poll_max_retries", DEFAULT_MAX_RETRIES))
    timeout = int(config.get("poll_request_timeout", DEFAULT_REQUEST_TIMEOUT))

    # ID des KI-Verarbeitet-Tags ermitteln (zum Ausfiltern bereits verarbeiteter Dokumente)
    ki_tag_id = _get_ki_tag_id(session, base, logger)

    # Dokumente ohne document_type = noch nicht verarbeitet (mit Retry)
    resp = _api_request_with_retry(
        session,
        f"{base}/api/documents/",
        max_retries=max_retries,
        timeout=timeout,
        logger=logger,
        params={"document_type__isnull": "true", "ordering": "added", "page_size": 50},
    )

    if resp is None:
        logger.error("[poll] Dokumentabfrage fehlgeschlagen – Abbruch")
        return

    all_docs = resp.json().get("results") or []

    # Bereits KI-verarbeitete Dokumente herausfiltern
    if ki_tag_id is not None:
        docs = [d for d in all_docs if ki_tag_id not in (d.get("tags") or [])]
        skipped = len(all_docs) - len(docs)
        if skipped:
            print(f"  {skipped} Dokument(e) bereits KI-verarbeitet – übersprungen.")
    else:
        docs = all_docs

    if not docs:
        print("Keine neuen Dokumente zur Verarbeitung.")
        return

    print_preview(docs, session, base)

    auto_consume = str(SCRIPT_DIR / "auto_consume.py")
    for doc in docs:
        doc_id = str(doc["id"])
        filename = doc.get("original_file_name") or f"doc_{doc_id}.pdf"
        env = {**os.environ, "DOCUMENT_ID": doc_id, "DOCUMENT_FILE_NAME": filename}
        subprocess.run([sys.executable, auto_consume], env=env, check=False)

    # Nachher: aktuellen Stand aller Dokumente anzeigen (mit Retry)
    resp2 = _api_request_with_retry(
        session,
        f"{base}/api/documents/",
        max_retries=max_retries,
        timeout=timeout,
        logger=logger,
        params={"ordering": "-added", "page_size": len(docs)},
    )
    if resp2:
        updated = {d["id"]: d for d in resp2.json().get("results", [])}
        print("\n" + "=" * 70)
        print("  ERGEBNIS nach Klassifikation")
        print("=" * 70)
        for doc in docs:
            d = updated.get(doc["id"], doc)
            title = d.get("title") or f"doc_{d['id']}"
            tag_ids = d.get("tags") or []
            tag_names: list[str] = []
            if tag_ids:
                try:
                    t = session.get(
                        f"{base}/api/tags/",
                        params={"id__in": ",".join(str(i) for i in tag_ids)},
                        timeout=10,
                    )
                    tag_names = [r["name"] for r in t.json().get("results", [])]
                except Exception:
                    tag_names = [str(i) for i in tag_ids]
            tag_str = "  ".join(f"[{n}]" for n in tag_names) if tag_names else "(keine Tags)"
            print(f"\n  ID {d['id']:>4}  |  {title[:55]}")
            print(f"           Tags: {tag_str}")
        print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
