#!/usr/bin/env python3
"""
Datenfresser — Folder Watcher
Überwacht einen Eingangsordner, erkennt Duplikate per MD5 und verschiebt
neue Dateien (mit OCR) automatisch in den Paperless-ngx consume-Ordner.

Konfiguration: /opt/paperless-ai/config.yaml
Log:           /data/datenfresser.log
"""

import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from duplicate_check import DuplicateChecker  # noqa: E402

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif"}

_ENV_OVERRIDES = {
    "datenfresser_path":            "DATENFRESSER_PATH",
    "datenfresser_duplicates_path": "DATENFRESSER_DUPLICATES_PATH",
    "datenfresser_poll_interval":   "DATENFRESSER_POLL_INTERVAL",
    "copy_scans_to":                "COPY_SCANS_TO",
    "ocr_lang":                     "OCR_LANG",
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg_path = SCRIPT_DIR.parent / "config.yaml"
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        cfg = {}

    for key, env_var in _ENV_OVERRIDES.items():
        val = os.environ.get(env_var)
        if val:
            cfg[key] = val

    return cfg


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("datenfresser")
    logger.setLevel(logging.INFO)

    fh = logging.handlers.RotatingFileHandler(
        Path("/data/datenfresser.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
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
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def is_stable(path: Path, wait_secs: float = 2.0) -> bool:
    """Prüft ob eine Datei vollständig geschrieben wurde (Größe stabil)."""
    try:
        size1 = path.stat().st_size
        time.sleep(wait_secs)
        size2 = path.stat().st_size
        return size1 == size2 and size1 > 0
    except OSError:
        return False


def has_text_layer(pdf_path: Path) -> bool:
    """Gibt True zurück wenn das PDF bereits einen Text-Layer hat."""
    try:
        result = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=15
        )
        return bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_ocr(src: Path, dest_dir: Path, ocr_lang: str, logger: logging.Logger) -> Path | None:
    """
    Wendet OCR an und gibt den Pfad der Ausgabedatei zurück.
    - PDF ohne Text-Layer → ocrmypdf (PDF mit Text-Layer)
    - Bild (JPG/PNG/TIFF)  → tesseract → PDF
    Gibt None zurück wenn OCR fehlgeschlagen.
    """
    ext = src.suffix.lower()
    out_name = src.stem + ".pdf"
    out_path = dest_dir / out_name

    if ext == ".pdf":
        if has_text_layer(src):
            logger.debug(f"{src.name}: Text-Layer vorhanden – kein OCR nötig")
            shutil.copy2(src, out_path)
            return out_path

        # OCR mit ocrmypdf
        if shutil.which("ocrmypdf"):
            logger.info(f"{src.name}: Starte ocrmypdf (lang={ocr_lang})")
            result = subprocess.run(
                ["ocrmypdf", "--language", ocr_lang, "--output-type", "pdfa",
                 "--skip-text", str(src), str(out_path)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                return out_path
            logger.warning(f"ocrmypdf fehlgeschlagen: {result.stderr[:200]}")
        else:
            logger.warning("ocrmypdf nicht gefunden – PDF ohne OCR kopiert")
            shutil.copy2(src, out_path)
            return out_path

    else:
        # Bild → Tesseract → PDF
        if shutil.which("tesseract"):
            logger.info(f"{src.name}: Starte tesseract OCR (lang={ocr_lang})")
            out_base = str(dest_dir / src.stem)
            result = subprocess.run(
                ["tesseract", str(src), out_base, "-l", ocr_lang, "pdf"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                return Path(out_base + ".pdf")
            logger.warning(f"tesseract fehlgeschlagen: {result.stderr[:200]}")
        else:
            logger.warning(f"tesseract nicht gefunden – {src.name} wird übersprungen")

    return None


# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------

def watch_once(
    watch_dir: Path,
    consume_dir: Path,
    dup_dir: Path,
    checker: DuplicateChecker,
    ocr_lang: str,
    seen: set,
    logger: logging.Logger,
) -> None:
    """Verarbeitet alle neuen Dateien in watch_dir."""
    try:
        entries = list(watch_dir.iterdir())
    except OSError as exc:
        logger.error(f"Kann Inbox nicht lesen: {exc}")
        return

    for entry in entries:
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if entry in seen:
            continue

        # Stabilitäts-Check
        if not is_stable(entry):
            logger.debug(f"{entry.name}: Datei noch nicht vollständig – warte")
            continue

        seen.add(entry)
        logger.info(f"Neue Datei erkannt: {entry.name}")

        # Duplikat-Check
        try:
            md5 = DuplicateChecker.calculate_md5(entry)
        except OSError as exc:
            logger.error(f"{entry.name}: MD5 konnte nicht berechnet werden: {exc}")
            continue

        is_dup, original = checker.is_duplicate(md5)
        if is_dup:
            dup_target = dup_dir / entry.name
            # Eindeutigen Namen vergeben falls Duplikat-Ordner schon denselben Namen hat
            if dup_target.exists():
                dup_target = dup_dir / f"{entry.stem}_{int(time.time())}{entry.suffix}"
            shutil.move(str(entry), dup_target)
            logger.warning(
                f"Duplikat erkannt: {entry.name!r} identisch mit {original!r} "
                f"→ verschoben nach {dup_dir.name}/"
            )
            continue

        # OCR + in consume verschieben
        out_file = run_ocr(entry, consume_dir, ocr_lang, logger)
        if out_file is None:
            logger.error(f"{entry.name}: OCR fehlgeschlagen – Datei bleibt in Inbox")
            seen.discard(entry)
            continue

        # Original aus Inbox entfernen (nur wenn OCR erfolgreich)
        try:
            entry.unlink()
        except OSError as exc:
            logger.warning(f"{entry.name}: Original konnte nicht gelöscht werden: {exc}")

        # Hash registrieren
        checker.register_document(md5, entry.name, doc_id="datenfresser")
        logger.info(f"{entry.name} → {out_file.name} in consume/ verschoben ✓")


def main() -> None:
    config = load_config()
    logger = setup_logging()

    watch_dir = Path(config.get("datenfresser_path", "/share/datenfresser/inbox"))
    consume_dir = Path(config.get("copy_scans_to", "/share/paperless/consume"))
    dup_dir = Path(config.get("datenfresser_duplicates_path", "/share/datenfresser/duplicates"))
    ocr_lang = config.get("ocr_lang", "deu+eng")
    poll_secs = int(config.get("datenfresser_poll_interval", 30))

    # Verzeichnisse anlegen
    for d in (watch_dir, dup_dir):
        d.mkdir(parents=True, exist_ok=True)

    if not consume_dir.exists():
        logger.warning(f"consume-Ordner existiert nicht: {consume_dir} – Datenfresser wartet")

    checker = DuplicateChecker(Path("/data/document_hashes.db"), logger)

    logger.info(
        f"Datenfresser gestartet | inbox={watch_dir} | consume={consume_dir} "
        f"| duplicates={dup_dir} | poll={poll_secs}s | lang={ocr_lang}"
    )

    seen: set = set()

    while True:
        if consume_dir.exists():
            watch_once(watch_dir, consume_dir, dup_dir, checker, ocr_lang, seen, logger)
        time.sleep(poll_secs)


if __name__ == "__main__":
    main()
