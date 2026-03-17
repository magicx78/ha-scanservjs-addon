#!/usr/bin/env python3
"""
Pollt Paperless-ngx auf neue unkategorisierte Dokumente
und ruft auto_consume.py fuer jedes auf.

Cron: */5 * * * * python3 /config/scripts/poll_new_docs.py
"""

import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

SCRIPT_DIR = Path(__file__).parent


def load_config() -> dict:
    with open(SCRIPT_DIR / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    config = load_config()
    base = config["paperless_url"].rstrip("/")
    token = config["paperless_token"]

    session = requests.Session()
    session.headers["Authorization"] = f"Token {token}"

    # Dokumente ohne document_type und ohne Tags = noch nicht verarbeitet
    resp = session.get(
        f"{base}/api/documents/",
        params={"document_type__isnull": "true", "ordering": "added", "page_size": 50},
        timeout=15,
    )
    resp.raise_for_status()
    docs = resp.json().get("results") or []

    if not docs:
        return

    auto_consume = str(SCRIPT_DIR / "auto_consume.py")
    for doc in docs:
        doc_id = str(doc["id"])
        filename = doc.get("original_file_name") or f"doc_{doc_id}.pdf"
        env = {**os.environ, "DOCUMENT_ID": doc_id, "DOCUMENT_FILE_NAME": filename}
        subprocess.run([sys.executable, auto_consume], env=env, check=False)


if __name__ == "__main__":
    main()
