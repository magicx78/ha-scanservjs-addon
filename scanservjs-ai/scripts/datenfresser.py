#!/usr/bin/env python3
"""
Datenfresser — Folder Watcher
Überwacht einen Eingangsordner, erkennt Duplikate per MD5 und verschiebt
neue Dateien (mit OCR) automatisch in den Paperless-ngx consume-Ordner.

Konfiguration: /opt/paperless-ai/config.yaml
Log:           /data/datenfresser.log
"""

import fcntl
import json
import logging
import logging.handlers
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import yaml

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from duplicate_check import DuplicateChecker  # noqa: E402
from claude_namer import ClaudeNamer  # noqa: E402
from paperless_api import PaperlessAPI  # noqa: E402
from ha_notify import HANotifier  # noqa: E402

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".doc", ".docx"}
LOCK_FILE = Path("/data/datenfresser.lock")
STATUS_FILE = Path("/data/datenfresser-status.json")
MAX_SEEN_SIZE = 10000  # Cleanup bei zu vielem
MAX_OCR_RETRIES = 3  # Max Versuche pro Datei bevor sie nach errors/ verschoben wird

_ENV_OVERRIDES = {
    "datenfresser_path":            "DATENFRESSER_PATH",
    "datenfresser_duplicates_path": "DATENFRESSER_DUPLICATES_PATH",
    "datenfresser_poll_interval":   "DATENFRESSER_POLL_INTERVAL",
    "copy_scans_to":                "COPY_SCANS_TO",
    "ocr_lang":                     "OCR_LANG",
}

DATENFRESSER_CACHE_DIR = Path("/share/datenfresser/cache")


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


def _convert_doc_to_pdf(src: Path, logger: logging.Logger) -> Optional[Path]:
    """Konvertiert DOC/DOCX nach PDF via LibreOffice headless."""
    if not shutil.which("libreoffice"):
        logger.error(f"{src.name}: libreoffice nicht gefunden – DOC/DOCX-Konvertierung nicht moeglich")
        return None

    tmp_dir = Path("/tmp/datenfresser_doc")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        logger.info(f"{src.name}: Konvertiere DOC/DOCX nach PDF via LibreOffice")
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf",
             "--outdir", str(tmp_dir), str(src)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.warning(f"{src.name}: LibreOffice-Konvertierung fehlgeschlagen: {result.stderr[:200]}")
            return None

        pdf_out = tmp_dir / (src.stem + ".pdf")
        if pdf_out.exists() and pdf_out.stat().st_size > 0:
            return pdf_out

        logger.warning(f"{src.name}: LibreOffice hat keine PDF erzeugt")
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"{src.name}: LibreOffice Timeout")
        return None
    except Exception as exc:
        logger.error(f"{src.name}: DOC-Konvertierung Fehler: {exc}")
        return None


def run_ocr(
    src: Path, dest_dir: Path, ocr_lang: str, logger: logging.Logger, max_retries: int = 2
) -> Optional[Path]:
    """
    Wendet OCR an und gibt den Pfad der Ausgabedatei zurück.
    - PDF ohne Text-Layer → ocrmypdf (PDF mit Text-Layer)
    - Bild (JPG/PNG/TIFF)  → tesseract → PDF
    Gibt None zurück wenn OCR fehlgeschlagen.
    """
    ext = src.suffix.lower()
    out_name = src.stem + ".pdf"
    out_path = dest_dir / out_name

    # --- DOC/DOCX: zuerst nach PDF konvertieren, dann wie PDF weiter ---
    if ext in (".doc", ".docx"):
        pdf_tmp = _convert_doc_to_pdf(src, logger)
        if pdf_tmp is None:
            return None
        # Konvertierte PDF als neues src verwenden
        try:
            shutil.copy2(str(pdf_tmp), str(out_path))
            pdf_tmp.unlink(missing_ok=True)
            return out_path
        except OSError as exc:
            logger.error(f"{src.name}: Fehler beim Kopieren der konvertierten PDF: {exc}")
            pdf_tmp.unlink(missing_ok=True)
            return None

    if ext == ".pdf":
        try:
            if has_text_layer(src):
                logger.debug(f"{src.name}: Text-Layer vorhanden – kein OCR nötig")
                shutil.copy2(src, out_path)
                return out_path
        except OSError as exc:
            logger.error(f"{src.name}: Fehler beim Text-Layer-Check: {exc}")
            return None

        # OCR mit ocrmypdf (mit Retry)
        if shutil.which("ocrmypdf"):
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"{src.name}: Starte ocrmypdf (Versuch {attempt}/{max_retries})")
                    result = subprocess.run(
                        ["ocrmypdf", "--language", ocr_lang, "--output-type", "pdfa",
                         "--skip-text", str(src), str(out_path)],
                        capture_output=True, text=True, timeout=180
                    )
                    if result.returncode == 0:
                        return out_path
                    if attempt < max_retries:
                        logger.warning(f"ocrmypdf Versuch {attempt} fehlgeschlagen – retry")
                        time.sleep(2)
                        continue
                    logger.warning(f"ocrmypdf fehlgeschlagen nach {max_retries} Versuchen: {result.stderr[:200]}")
                except subprocess.TimeoutExpired:
                    logger.warning(f"{src.name}: ocrmypdf Timeout (Versuch {attempt})")
                    if attempt == max_retries:
                        return None
                except Exception as exc:
                    logger.error(f"{src.name}: OCR-Fehler: {exc}")
                    return None
        else:
            logger.warning("ocrmypdf nicht gefunden – PDF ohne OCR kopiert")
            try:
                shutil.copy2(src, out_path)
                return out_path
            except OSError as exc:
                logger.error(f"{src.name}: Fehler beim Kopieren: {exc}")
                return None

    else:
        # Bild → Tesseract → PDF (mit Retry)
        if shutil.which("tesseract"):
            for attempt in range(1, max_retries + 1):
                try:
                    out_base = str(dest_dir / src.stem)
                    logger.info(f"{src.name}: Starte tesseract OCR (Versuch {attempt}/{max_retries})")
                    result = subprocess.run(
                        ["tesseract", str(src), out_base, "-l", ocr_lang, "pdf"],
                        capture_output=True, text=True, timeout=120
                    )
                    if result.returncode == 0:
                        return Path(out_base + ".pdf")
                    if attempt < max_retries:
                        logger.warning(f"tesseract Versuch {attempt} fehlgeschlagen – retry")
                        time.sleep(2)
                        continue
                    logger.warning(f"tesseract fehlgeschlagen nach {max_retries} Versuchen: {result.stderr[:200]}")
                except subprocess.TimeoutExpired:
                    logger.warning(f"{src.name}: tesseract Timeout (Versuch {attempt})")
                    if attempt == max_retries:
                        return None
                except Exception as exc:
                    logger.error(f"{src.name}: tesseract-Fehler: {exc}")
                    return None
        else:
            logger.warning(f"tesseract nicht gefunden – {src.name} wird übersprungen")

    return None


def extract_text_from_pdf(pdf_path: Path, logger: logging.Logger) -> str:
    """Extrahiert Text aus PDF (z.B. nach OCR)."""
    try:
        result = subprocess.run(
            ["pdftotext", str(pdf_path), "-"],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as exc:
        logger.debug(f"{pdf_path.name}: Text-Extraktion fehlgeschlagen: {exc}")
        return ""


def sanitize(text: str) -> str:
    """Entfernt Umlaute und Sonderzeichen für Dateinamen."""
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


def write_ki_status(filename: str, title: str, tags: list, konfidenz: float, kategorie: str) -> None:
    """Schreibt Echtzeit-KI-Status für UI-Widget (custom.js)."""
    try:
        status = {
            "last_doc": {
                "filename": filename,
                "title": title,
                "tags": tags or [],
                "konfidenz": konfidenz,
                "kategorie": kategorie,
            },
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        status_file = Path("/data/ki-status.json")
        status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def write_datenfresser_status(
    watch_dir: Path, dup_dir: Path, error_dir: Path, unsupported_dir: Path,
    last_doc: str = "", last_error: str = "",
) -> None:
    """Schreibt Datenfresser-Status als JSON fuer HA-Sensoren."""
    def _count_files(d: Path) -> int:
        try:
            return sum(1 for f in d.iterdir() if f.is_file()) if d.exists() else 0
        except OSError:
            return 0

    try:
        status = {
            "inbox_count": _count_files(watch_dir),
            "duplicate_count": _count_files(dup_dir),
            "error_count": _count_files(error_dir),
            "unsupported_count": _count_files(unsupported_dir),
            "last_document": last_doc,
            "last_error": last_error,
            "running": True,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def move_to_dir(src: Path, dest_dir: Path, logger: logging.Logger) -> Optional[Path]:
    """Verschiebt eine Datei in einen Zielordner (mit Namenskollision-Schutz)."""
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / src.name
        if target.exists():
            target = dest_dir / f"{src.stem}_{int(time.time())}{src.suffix}"
        shutil.move(str(src), str(target))
        return target
    except OSError as exc:
        logger.error(f"{src.name}: Verschieben nach {dest_dir} fehlgeschlagen: {exc}")
        return None


# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------

def watch_once(
    watch_dir: Path,
    consume_dir: Path,
    dup_dir: Path,
    error_dir: Path,
    unsupported_dir: Path,
    checker: DuplicateChecker,
    ocr_lang: str,
    seen: set,
    retry_counts: dict,
    logger: logging.Logger,
    namer: Optional["ClaudeNamer"] = None,
    paperless: Optional["PaperlessAPI"] = None,
    notifier: Optional["HANotifier"] = None,
) -> None:
    """Verarbeitet alle neuen Dateien in watch_dir."""
    try:
        entries = list(watch_dir.iterdir())
    except OSError as exc:
        logger.error(f"Kann Inbox nicht lesen: {exc}")
        return

    # Cleanup seen-Set und retry_counts wenn zu viele Einträge
    if len(seen) > MAX_SEEN_SIZE:
        logger.debug(f"Cleanup seen-Set ({len(seen)} Eintraege)")
        seen.clear()
    if len(retry_counts) > 1000:
        logger.debug(f"Cleanup retry_counts ({len(retry_counts)} Eintraege)")
        retry_counts.clear()

    last_doc = ""
    last_error = ""

    for entry in entries:
        try:
            if not entry.is_file():
                continue
            if entry.name.startswith("."):
                continue  # Versteckte/temporaere Dateien immer ignorieren

            # Unsupported-Dateien erkennen und verschieben
            if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                if not is_stable(entry):
                    continue
                moved = move_to_dir(entry, unsupported_dir, logger)
                if moved:
                    logger.warning(
                        f"{entry.name}: Format nicht unterstuetzt ({entry.suffix}) "
                        f"→ verschoben nach {unsupported_dir.name}/"
                    )
                    last_error = f"Nicht unterstuetzt: {entry.name}"
                    if notifier:
                        notifier.notify_warning(
                            f"Datei {entry.name!r} hat ein nicht unterstuetztes Format "
                            f"({entry.suffix}) und wurde nach {unsupported_dir.name}/ verschoben."
                        )
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
                if dup_target.exists():
                    dup_target = dup_dir / f"{entry.stem}_{int(time.time())}{entry.suffix}"
                try:
                    shutil.copy2(str(entry), str(dup_target))
                    logger.warning(
                        f"Duplikat erkannt: {entry.name!r} identisch mit {original!r} "
                        f"→ Kopie nach {dup_dir.name}/"
                    )
                except OSError as exc:
                    logger.error(f"{entry.name}: Fehler beim Kopieren zu Duplikaten: {exc}")
                is_dup_flag = True
            else:
                is_dup_flag = False

            # OCR + in consume verschieben
            out_file = run_ocr(entry, consume_dir, ocr_lang, logger)
            if out_file is None:
                # Retry-Counter prüfen
                file_key = str(entry)
                retry_counts[file_key] = retry_counts.get(file_key, 0) + 1
                if retry_counts[file_key] >= MAX_OCR_RETRIES:
                    # Nach N Versuchen: nach errors/ verschieben
                    moved = move_to_dir(entry, error_dir, logger)
                    if moved:
                        logger.error(
                            f"{entry.name}: OCR fehlgeschlagen nach {MAX_OCR_RETRIES} Versuchen "
                            f"→ verschoben nach {error_dir.name}/"
                        )
                        last_error = f"OCR fehlgeschlagen: {entry.name}"
                        if notifier:
                            notifier.notify_warning(
                                f"OCR fuer {entry.name!r} nach {MAX_OCR_RETRIES} Versuchen fehlgeschlagen. "
                                f"Datei nach {error_dir.name}/ verschoben."
                            )
                    retry_counts.pop(file_key, None)
                    seen.discard(entry)
                else:
                    logger.warning(
                        f"{entry.name}: OCR fehlgeschlagen (Versuch {retry_counts[file_key]}/{MAX_OCR_RETRIES}) "
                        f"– naechster Versuch beim naechsten Poll"
                    )
                    seen.discard(entry)
                continue

            # Retry-Counter zurücksetzen bei Erfolg
            retry_counts.pop(str(entry), None)

            # Original aus Inbox entfernen
            try:
                entry.unlink()
            except OSError as exc:
                logger.warning(f"{entry.name}: Original konnte nicht gelöscht werden: {exc}")

            # Hash registrieren
            checker.register_document(md5, entry.name, doc_id="datenfresser")

            # --- Claude-Klassifikation (Optional) ---
            classif_json = None
            if namer and paperless:
                try:
                    if is_dup_flag:
                        classif_json = {
                            "filename": out_file.name,
                            "is_duplicate": True,
                            "original": original,
                        }
                        logger.debug(f"{out_file.name}: Duplikat-Marker gespeichert")
                    else:
                        ocr_text = extract_text_from_pdf(out_file, logger)
                        if ocr_text and ocr_text.strip():
                            result = namer.classify(ocr_text[:5000])
                            title = build_title(result)
                            classif_json = {
                                "filename": out_file.name,
                                "titel": title,
                                "kategorie": result.get("kategorie"),
                                "tags": result.get("tags") or [],
                                "firma": result.get("firma"),
                                "person": result.get("person"),
                                "datum": result.get("datum"),
                                "konfidenz": result.get("konfidenz"),
                            }
                        else:
                            logger.debug(f"{out_file.name}: Kein OCR-Text für Klassifikation")

                    if classif_json:
                        try:
                            DATENFRESSER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                            json_path = DATENFRESSER_CACHE_DIR / out_file.with_suffix(".json").name
                            json_path.write_text(json.dumps(classif_json, ensure_ascii=False), encoding="utf-8")
                            logger.debug(f"{out_file.name}: JSON in Cache geschrieben")
                        except OSError as exc:
                            logger.warning(f"{out_file.name}: Fehler beim Schreiben von Cache-JSON: {exc}")
                except Exception as exc:
                    logger.warning(f"{out_file.name}: Klassifikation fehlgeschlagen: {exc}")

            last_doc = out_file.name
            logger.info(f"{entry.name} → {out_file.name} in consume/ verschoben")

            # UI-Status aktualisieren
            if classif_json:
                write_ki_status(
                    filename=out_file.name,
                    title=classif_json.get("titel") or out_file.stem,
                    tags=classif_json.get("tags") or [],
                    konfidenz=classif_json.get("konfidenz") or 0,
                    kategorie=classif_json.get("kategorie") or "Unbekannt",
                )

            # HA-Automation triggern wenn konfiguriert
            if notifier:
                notifier.trigger_automation()

        except Exception as exc:
            logger.error(f"Unerwarteter Fehler bei {entry.name}: {exc}", exc_info=True)
            seen.discard(entry)
            continue

    # Status-Datei aktualisieren (nach jedem Poll-Durchlauf)
    write_datenfresser_status(
        watch_dir, dup_dir, error_dir, unsupported_dir,
        last_doc=last_doc, last_error=last_error,
    )


def main() -> None:
    # Lock-File: verhindert parallele Datenfresser-Instanzen
    lock_fh = None
    try:
        lock_fh = open(LOCK_FILE, "w")
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Datenfresser läuft bereits – Abbruch.", file=sys.stderr)
        if lock_fh:
            lock_fh.close()
        sys.exit(1)
    except OSError as exc:
        print(f"Lock-Fehler: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config()
        logger = setup_logging()

        watch_dir = Path(config.get("datenfresser_path", "/share/datenfresser/inbox"))
        consume_dir = Path(config.get("copy_scans_to", "/share/paperless/consume"))
        dup_dir = Path(config.get("datenfresser_duplicates_path", "/share/datenfresser/duplicates"))
        error_dir = Path(config.get("datenfresser_errors_path", "/share/datenfresser/errors"))
        unsupported_dir = Path(config.get("datenfresser_unsupported_path", "/share/datenfresser/unsupported"))
        ocr_lang = config.get("ocr_lang", "deu+eng")
        poll_secs = int(config.get("datenfresser_poll_interval", 30))

        # Validierung
        if poll_secs < 5:
            logger.warning(f"poll_interval {poll_secs}s ist zu kurz – setze auf 5s")
            poll_secs = 5

        # Verzeichnisse anlegen
        for d in (watch_dir, dup_dir, error_dir, unsupported_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                logger.error(f"Kann Verzeichnis nicht erstellen: {d} – {exc}")
                sys.exit(1)

        if not consume_dir.exists():
            logger.warning(f"consume-Ordner existiert nicht: {consume_dir} – Datenfresser wartet")

        checker = DuplicateChecker(Path("/data/document_hashes.db"), logger)
        notifier = HANotifier(config, logger)

        # --- Claude-Klassifikation (Optional) ---
        namer = None
        paperless = None
        if config.get("claude_access_type") != "none" and config.get("anthropic_api_key"):
            try:
                namer = ClaudeNamer(config, logger)
                paperless = PaperlessAPI(config, logger)
                logger.info("Claude-Klassifikation aktiviert")
            except Exception as exc:
                logger.warning(f"Claude-Klassifikation nicht verfügbar: {exc}")
                namer = None
                paperless = None
        else:
            logger.info("Claude-Klassifikation deaktiviert (claude_access_type=none oder kein API-Key)")

        logger.info(
            f"Datenfresser gestartet | inbox={watch_dir} | consume={consume_dir} "
            f"| duplicates={dup_dir} | errors={error_dir} | unsupported={unsupported_dir} "
            f"| poll={poll_secs}s | lang={ocr_lang}"
        )

        seen: set = set()
        retry_counts: dict = {}  # {Dateipfad: Anzahl fehlgeschlagener OCR-Versuche}
        consecutive_errors = 0
        max_consecutive_errors = 10

        while True:
            try:
                if consume_dir.exists():
                    watch_once(
                        watch_dir, consume_dir, dup_dir, error_dir, unsupported_dir,
                        checker, ocr_lang, seen, retry_counts, logger,
                        namer, paperless, notifier,
                    )
                    consecutive_errors = 0
                else:
                    if consecutive_errors == 0:
                        logger.debug(f"consume-Ordner nicht vorhanden – warte")
                    consecutive_errors += 1

                time.sleep(poll_secs)

            except KeyboardInterrupt:
                logger.info("Datenfresser beendet (Interrupt)")
                break
            except Exception as exc:
                consecutive_errors += 1
                logger.error(f"Fehler in watch_once [{consecutive_errors}/{max_consecutive_errors}]: {exc}", exc_info=True)

                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"Zu viele Fehler ({max_consecutive_errors}) – Datenfresser beendet")
                    sys.exit(1)

                time.sleep(min(poll_secs * 2, 60))

    except Exception as exc:
        if lock_fh:
            logger.critical(f"Kritischer Fehler: {exc}", exc_info=True)
        sys.exit(1)

    finally:
        if notifier:
            notifier.close()
        if lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_UN)
            lock_fh.close()


if __name__ == "__main__":
    main()
