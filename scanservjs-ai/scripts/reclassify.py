#!/usr/bin/env python3
"""
Re-Classify: Bestehende Paperless-Dokumente nachtraeglich per KI neu klassifizieren.

Holt Dokumente aus Paperless-ngx, schickt den OCR-Text durch die KI
(Claude oder Ollama) und aktualisiert Titel, Tags, Korrespondent und Dokumenttyp.

Filter-Optionen (reclassify_filter):
  ""               — Dokumente OHNE "KI-Verarbeitet" und OHNE "Re-Klassifiziert" Tag
  "all"            — Alle Dokumente (bis max_docs)
  "untagged"       — Dokumente ohne Tags
  "tag:Sonstiges"  — Dokumente mit bestimmtem Tag
  "older_than:30d" — Dokumente aelter als N Tage

Sicherheit:
  - max_docs begrenzt Kosten und Laufzeit (Standard: 50)
  - 2s Pause zwischen Dokumenten (Rate-Limiting)
  - Cache wird genutzt (identische OCR-Texte kosten keine API-Calls)
  - "Re-Klassifiziert" Tag verhindert doppelte Verarbeitung
"""

import json
import logging
import logging.handlers
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
import yaml

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from claude_namer import ClaudeNamer  # noqa: E402
from paperless_api import PaperlessAPI  # noqa: E402
from ha_notify import HANotifier  # noqa: E402

# ---------------------------------------------------------------------------
# KI-Status (gleich wie auto_consume.py)
# ---------------------------------------------------------------------------

_KI_STATUS_PATHS = [
    Path("/usr/lib/scanservjs/client/dist/ki-status.json"),
    Path("/app/client/dist/ki-status.json"),
]


def _write_ki_status(title: str, tags: list, doc_id: int) -> None:
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "last_doc": {"id": doc_id, "title": title, "tags": tags},
    }
    for p in _KI_STATUS_PATHS:
        try:
            if p.parent.exists():
                p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def sanitize(text: str) -> str:
    for src, dst in (
        ("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"),
        ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"),
        (" ", "-"),
    ):
        text = text.replace(src, dst)
    text = re.sub(r"[^\w\-\.]", "", text)
    return text


def build_title(result: dict) -> str:
    datum = result.get("datum") or "0000-00-00"
    kategorie = sanitize(result.get("kategorie") or "Sonstiges")
    beschreibung = sanitize(result.get("beschreibung") or "Unbekannt")
    tags = [t for t in (result.get("tags") or []) if t][:10]
    tag_str = "".join(f"[{sanitize(str(t))}]" for t in tags)
    parts = [datum, kategorie, beschreibung]
    if tag_str:
        parts.append(tag_str)
    return "_".join(parts)[:128]


def load_config() -> dict:
    cfg_path = SCRIPT_DIR / "config.yaml"
    try:
        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        cfg = {}

    for key, env_var in (
        ("paperless_url", "PAPERLESS_URL"),
        ("paperless_token", "PAPERLESS_TOKEN"),
        ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("ha_url", "HA_URL"),
        ("ha_token", "HA_TOKEN"),
        ("ha_token", "SUPERVISOR_TOKEN"),
    ):
        val = os.environ.get(env_var)
        if val:
            cfg[key] = val

    if not cfg.get("ha_url") and os.environ.get("SUPERVISOR_TOKEN"):
        cfg["ha_url"] = "http://supervisor/core"

    return cfg


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("reclassify")
    logger.setLevel(logging.INFO)

    fh = logging.handlers.RotatingFileHandler(
        Path("/data/reclassify.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(sh)

    return logger


# ---------------------------------------------------------------------------
# Paperless-Dokumente abrufen
# ---------------------------------------------------------------------------

def _get_tag_id(session: requests.Session, api_base: str, tag_name: str) -> Optional[int]:
    try:
        resp = session.get(f"{api_base}/tags/", params={"name__iexact": tag_name}, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if results:
            return results[0]["id"]
    except requests.RequestException:
        pass
    return None


def get_documents_to_reclassify(
    session: requests.Session,
    api_base: str,
    filter_str: str,
    max_docs: int,
    logger: logging.Logger,
) -> list:
    """Holt Dokumente aus Paperless basierend auf Filter."""
    params = {"ordering": "added", "page_size": min(max_docs, 100)}

    if not filter_str or filter_str == "":
        # Default: Dokumente OHNE "KI-Verarbeitet" UND OHNE "Re-Klassifiziert"
        exclude_ids = []
        for tag_name in ("KI-Verarbeitet", "Re-Klassifiziert"):
            tag_id = _get_tag_id(session, api_base, tag_name)
            if tag_id:
                exclude_ids.append(tag_id)
        if exclude_ids:
            params["tags__id__none"] = ",".join(str(i) for i in exclude_ids)

    elif filter_str == "all":
        # Alle Dokumente, aber nicht schon Re-Klassifiziert
        reclassified_id = _get_tag_id(session, api_base, "Re-Klassifiziert")
        if reclassified_id:
            params["tags__id__none"] = str(reclassified_id)

    elif filter_str == "untagged":
        params["is_tagged"] = "false"

    elif filter_str.startswith("tag:"):
        tag_name = filter_str[4:].strip()
        tag_id = _get_tag_id(session, api_base, tag_name)
        if tag_id:
            params["tags__id__all"] = str(tag_id)
        else:
            logger.warning(f"Tag '{tag_name}' nicht in Paperless gefunden")
            return []

    elif filter_str.startswith("older_than:"):
        match = re.match(r"older_than:(\d+)d", filter_str)
        if match:
            days = int(match.group(1))
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            params["created__date__lt"] = cutoff
        else:
            logger.warning(f"Ungueltiges Filter-Format: {filter_str}")
            return []

    else:
        logger.warning(f"Unbekannter Filter: {filter_str} — verwende Default")
        return get_documents_to_reclassify(session, api_base, "", max_docs, logger)

    docs = []
    url = f"{api_base}/documents/"
    try:
        while url and len(docs) < max_docs:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            docs.extend(data.get("results", []))
            url = data.get("next")
            params = {}  # next-URL enthaelt bereits alle Parameter
    except requests.RequestException as exc:
        logger.error(f"Fehler beim Abrufen der Dokumente: {exc}")

    return docs[:max_docs]


# ---------------------------------------------------------------------------
# Einzelnes Dokument re-klassifizieren
# ---------------------------------------------------------------------------

def reclassify_document(
    doc: dict,
    namer: ClaudeNamer,
    paperless: PaperlessAPI,
    min_konfidenz: float,
    logger: logging.Logger,
) -> bool:
    doc_id = str(doc["id"])
    old_title = doc.get("title", "?")

    # 1. OCR-Text laden
    ocr_text = paperless.get_document_content(doc_id)
    if not ocr_text or len(ocr_text.strip()) < 20:
        logger.warning(f"Doc {doc_id} ({old_title}): Kein/zu wenig OCR-Text — uebersprungen")
        return False

    # 2. Klassifizieren
    try:
        result = namer.classify(ocr_text[:5000])
    except Exception as exc:
        logger.error(f"Doc {doc_id} ({old_title}): Klassifikation fehlgeschlagen: {exc}")
        return False

    if not result or result.get("konfidenz", 0) == 0.0:
        logger.warning(f"Doc {doc_id} ({old_title}): KI-Fallback — uebersprungen")
        return False

    # 3. Titel bauen
    new_title = build_title(result)

    # 4. Metadaten in Paperless aktualisieren
    success = paperless.update_document(
        doc_id=doc_id,
        title=new_title,
        correspondent=result.get("firma") or result.get("person"),
        document_type=result.get("kategorie"),
        tags=result.get("tags") or [],
        created=result.get("datum"),
    )

    if not success:
        logger.error(f"Doc {doc_id}: Update fehlgeschlagen")
        return False

    # 5. Tags setzen
    paperless.add_tag(doc_id, "Re-Klassifiziert")

    konfidenz = result.get("konfidenz", 0.5)
    if konfidenz < min_konfidenz:
        paperless.add_tag(doc_id, "Pruefen")

    # 6. KI-Status aktualisieren
    _write_ki_status(new_title, result.get("tags", []), doc["id"])

    logger.info(
        f"Doc {doc_id}: '{old_title}' -> '{new_title}' "
        f"(konfidenz={konfidenz:.2f}, tags={result.get('tags', [])})"
    )
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logger = setup_logging()
    config = load_config()

    access_type = config.get("claude_access_type", "none")
    if access_type == "none":
        logger.info("Re-Classify: KI deaktiviert — nichts zu tun")
        return

    if access_type in ("api_key", "pro_plan") and not config.get("anthropic_api_key"):
        logger.error("Re-Classify: API-Key fehlt")
        return

    if not config.get("paperless_url") or not config.get("paperless_token"):
        logger.error("Re-Classify: Paperless-URL oder Token fehlt")
        return

    filter_str = config.get("reclassify_filter", "")
    max_docs = int(config.get("reclassify_max_docs", 50))
    min_konfidenz = float(config.get("min_konfidenz", 0.7))

    logger.info(f"Re-Classify gestartet | filter={filter_str or '(default)'} | max_docs={max_docs}")

    try:
        namer = ClaudeNamer(config, logger)
    except Exception as exc:
        logger.error(f"KI-Initialisierung fehlgeschlagen: {exc}")
        return

    paperless = PaperlessAPI(config, logger)
    notifier = HANotifier(config, logger)

    # Paperless-Session fuer Filter-Abfragen
    base = config["paperless_url"].rstrip("/")
    api_base = f"{base}/api"
    filter_session = requests.Session()
    filter_session.headers.update({
        "Authorization": f"Token {config['paperless_token']}",
        "Content-Type": "application/json",
    })

    docs = get_documents_to_reclassify(filter_session, api_base, filter_str, max_docs, logger)
    logger.info(f"Re-Classify: {len(docs)} Dokumente gefunden")

    if not docs:
        logger.info("Re-Classify: Keine Dokumente zum Verarbeiten")
        filter_session.close()
        notifier.close()
        return

    success = 0
    errors = 0
    for i, doc in enumerate(docs, 1):
        logger.info(f"Re-Classify [{i}/{len(docs)}]: Doc {doc['id']} — {doc.get('title', '?')}")
        if reclassify_document(doc, namer, paperless, min_konfidenz, logger):
            success += 1
        else:
            errors += 1

        # Rate-Limiting: 2s Pause zwischen Dokumenten
        if i < len(docs):
            time.sleep(2)

    summary = f"Re-Classify abgeschlossen: {success}/{len(docs)} erfolgreich"
    if errors:
        summary += f", {errors} Fehler"
    logger.info(summary)

    try:
        notifier.notify(summary)
    except Exception:
        pass
    finally:
        filter_session.close()
        notifier.close()


if __name__ == "__main__":
    main()
