#!/usr/bin/env python3
"""
Pollt Paperless-ngx auf neue unkategorisierte Dokumente
und ruft auto_consume.py fuer jedes auf.

Cron: */5 * * * * python3 /config/scripts/poll_new_docs.py
"""

import fcntl
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

SCRIPT_DIR = Path(__file__).parent
LOCK_FILE = SCRIPT_DIR / "poll_new_docs.lock"

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


def _run() -> None:
    config = load_config()
    base = config["paperless_url"].rstrip("/")
    token = config["paperless_token"]

    session = requests.Session()
    session.headers["Authorization"] = f"Token {token}"

    # Dokumente ohne document_type = noch nicht verarbeitet
    resp = session.get(
        f"{base}/api/documents/",
        params={"document_type__isnull": "true", "ordering": "added", "page_size": 50},
        timeout=15,
    )
    resp.raise_for_status()
    docs = resp.json().get("results") or []

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

    # Nachher: aktuellen Stand aller Dokumente anzeigen
    resp2 = session.get(
        f"{base}/api/documents/",
        params={"ordering": "-added", "page_size": len(docs)},
        timeout=15,
    )
    if resp2.ok:
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
