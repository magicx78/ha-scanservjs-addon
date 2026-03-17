#!/usr/bin/env python3
"""
Paperless-ngx Post-Consumption Script
Automatische KI-gestuetzte Dokumentenklassifikation via Claude API

Konfiguration: /config/scripts/config.yaml
Log:           /config/scripts/auto_consume.log
"""

import logging
import logging.handlers
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

import yaml  # noqa: E402 (nach sys.path-Setup)

from claude_namer import ClaudeNamer
from duplicate_check import DuplicateChecker
from ha_notify import HANotifier
from paperless_api import PaperlessAPI


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg_path = SCRIPT_DIR / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def setup_logging(log_level: str) -> logging.Logger:
    logger = logging.getLogger("auto_consume")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Rolling-Logfile (5 MB, 3 Backups)
    file_handler = logging.handlers.RotatingFileHandler(
        SCRIPT_DIR / "auto_consume.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    # Zusaetzlich stderr, damit Paperless den Output ins Container-Log schreibt
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(stderr_handler)

    return logger


def sanitize(text: str) -> str:
    """Entfernt Umlaute und Sonderzeichen fuer Dateinamen.

    Regeln:  ä→ae  ö→oe  ü→ue  ß→ss  Ä→Ae  Ö→Oe  Ü→Ue
             Leerzeichen → Bindestrich
             alle weiteren Nicht-Wortzeichen (ausser -.) entfernen
    """
    for src, dst in (
        ("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"),
        ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"),
        (" ", "-"),
    ):
        text = text.replace(src, dst)
    text = re.sub(r"[^\w\-\.]", "", text)
    return text


def build_title(result: dict) -> str:
    """Baut Dokumententitel nach Schema:
    JJJJ-MM-TT_Kategorie_Beschreibung_[Tag1][Tag2]...[Tag10]
    """
    datum = result.get("datum") or "0000-00-00"
    kategorie = sanitize(result.get("kategorie") or "Sonstiges")
    beschreibung = sanitize(result.get("beschreibung") or "Unbekannt")
    tags = [t for t in (result.get("tags") or []) if t][:10]
    tag_str = "".join(f"[{sanitize(str(t))}]" for t in tags)

    parts = [datum, kategorie, beschreibung]
    if tag_str:
        parts.append(tag_str)
    return "_".join(parts)[:128]


# ---------------------------------------------------------------------------
# Hauptlogik
# ---------------------------------------------------------------------------

def main() -> None:
    # Konfiguration laden
    try:
        config = load_config()
    except Exception as exc:
        print(f"[CRITICAL] config.yaml konnte nicht geladen werden: {exc}", file=sys.stderr)
        sys.exit(1)

    logger = setup_logging(config.get("log_level", "INFO"))

    # Paperless-Umgebungsvariablen
    doc_id = os.environ.get("DOCUMENT_ID")
    doc_filename = os.environ.get("DOCUMENT_FILE_NAME", "unknown.pdf")
    doc_source = os.environ.get("DOCUMENT_SOURCE_PATH", "")

    if not doc_id:
        logger.error("DOCUMENT_ID nicht gesetzt – Script wird beendet")
        sys.exit(1)

    logger.info(f"Verarbeite Dokument ID={doc_id} | Datei={doc_filename}")

    paperless = PaperlessAPI(config, logger)
    namer = ClaudeNamer(config, logger)
    notifier = HANotifier(config, logger)
    checker = DuplicateChecker(SCRIPT_DIR / "document_hashes.db", logger)

    try:
        # --- 1. Duplikat-Erkennung ---
        md5 = None
        source_path = Path(doc_source) if doc_source else None

        if source_path and source_path.exists():
            md5 = checker.calculate_md5(source_path)
            is_dup, original = checker.is_duplicate(md5)
            if is_dup:
                logger.warning(f"Duplikat erkannt: {doc_filename!r} identisch mit {original!r}")
                paperless.add_tag(doc_id, "Duplikat")
                notifier.notify_duplicate(doc_filename, original)
                return
        else:
            logger.warning(f"Quelldatei nicht erreichbar: {doc_source!r}")

        # --- 2. OCR-Text holen ---
        ocr_text = paperless.get_document_content(doc_id)

        if not ocr_text and source_path and source_path.exists():
            logger.info("Paperless-Content leer – versuche PDF-Direktextraktion")
            try:
                from pdfminer.high_level import extract_text as pdf_extract  # type: ignore
                ocr_text = pdf_extract(str(source_path), maxpages=2) or ""
            except Exception as exc:
                logger.warning(f"PDF-Fallback fehlgeschlagen: {exc}")

        if not (ocr_text and ocr_text.strip()):
            logger.warning("Kein OCR-Text verfuegbar – Dokument wird mit [Pruefen] markiert")
            paperless.add_tag(doc_id, "Pruefen")
            notifier.notify_warning(
                f"Kein OCR-Text fuer Dokument {doc_id} ({doc_filename}) – bitte manuell pruefen"
            )
            return

        # --- 3. Claude API: Klassifikation ---
        result = namer.classify(ocr_text[:3000])

        # --- 4. Paperless-Metadaten aktualisieren ---
        title = build_title(result)
        paperless.update_document(
            doc_id=doc_id,
            title=title,
            correspondent=result.get("firma") or result.get("person"),
            document_type=result.get("kategorie"),
            tags=result.get("tags") or [],
            created=result.get("datum"),
        )

        # --- 5. Konfidenz-Check ---
        konfidenz: float = float(result.get("konfidenz") or 1.0)
        min_konfidenz: float = float(config.get("min_konfidenz", 0.7))

        if konfidenz < min_konfidenz:
            logger.warning(
                f"Niedrige Konfidenz ({konfidenz:.0%}) fuer {title!r} – Tag [Pruefen] wird gesetzt"
            )
            paperless.add_tag(doc_id, "Pruefen")
            notifier.notify_warning(
                f"Konfidenz {konfidenz:.0%} fuer \u201e{title}\u201c – bitte manuell pruefen"
            )

        # --- 6. Hash registrieren ---
        if md5:
            checker.register_document(md5, doc_filename, doc_id)

        # --- 7. Erfolgs-Benachrichtigung ---
        notifier.notify_success(title, result.get("kategorie", "?"), konfidenz)
        logger.info(f"Dokument {doc_id} erfolgreich verarbeitet: {title}")

    except Exception as exc:
        # Paperless laeuft weiter – kein sys.exit(1)
        logger.error(
            f"Unbehandelter Fehler bei Dokument {doc_id}: {exc}",
            exc_info=True,
        )


if __name__ == "__main__":
    main()
