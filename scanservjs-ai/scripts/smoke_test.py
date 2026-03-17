#!/usr/bin/env python3
"""
Smoke-Test fuer scanservjs-ai KI-Scripts
Testet alle kritischen Pfade ohne echte Netzwerkverbindungen.

Ausfuehren:  python3 smoke_test.py
Erwartetes Ergebnis: alle Tests PASS
"""

import sys
import os
import platform
import tempfile
import traceback
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"
PASS = "[PASS]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"
results = []


def test(name: str, skip_on_windows: bool = False):
    """Decorator: faengt Ausnahmen und protokolliert Ergebnis."""
    def decorator(fn):
        if skip_on_windows and IS_WINDOWS:
            results.append((SKIP, f"{name} (Windows-inkompatibel, wird im Container getestet)"))
            return fn
        try:
            fn()
            results.append((PASS, name))
        except Exception as exc:
            results.append((FAIL, f"{name}: {exc}"))
            traceback.print_exc()
        return fn
    return decorator


# ---------------------------------------------------------------------------
# TEST 1: Imports aller Module
# ---------------------------------------------------------------------------

@test("Imports: alle Module importierbar")
def _():
    sys.path.insert(0, str(Path(__file__).parent))
    import yaml  # noqa
    import anthropic  # noqa
    import requests  # noqa
    from duplicate_check import DuplicateChecker  # noqa
    from ha_notify import HANotifier  # noqa
    from paperless_api import PaperlessAPI  # noqa
    from claude_namer import ClaudeNamer  # noqa


# ---------------------------------------------------------------------------
# TEST 2: ClaudeNamer – Modell-ID korrekt
# ---------------------------------------------------------------------------

@test("ClaudeNamer: Modell-ID ist claude-haiku-4-5-20251001")
def _():
    src = (Path(__file__).parent / "claude_namer.py").read_text()
    assert "claude-haiku-4-5-20251001" in src, "Falsches Modell gefunden!"
    # Sicherstellen dass alte ID nicht mehr vorkommt (ohne die korrekte)
    old_count = src.count("claude-haiku-4-5\"")
    assert old_count == 0, f"Alte Modell-ID noch {old_count}x vorhanden!"


# ---------------------------------------------------------------------------
# TEST 3: ClaudeNamer – Fallback bei fehlgeschlagenen API-Calls
# ---------------------------------------------------------------------------

@test("ClaudeNamer: FALLBACK_RESULT bei fehlgeschlagenen API-Calls")
def _():
    sys.path.insert(0, str(Path(__file__).parent))
    from claude_namer import ClaudeNamer, FALLBACK_RESULT
    import logging

    logger = logging.getLogger("test")
    config = {"anthropic_api_key": "test-key-invalid"}
    namer = ClaudeNamer(config, logger)

    # Simuliere fehlgeschlagene API-Calls durch Monkeypatching
    namer._call_with_retry = lambda *a, **kw: None  # type: ignore

    result = namer.classify("Test-Dokument Inhalt")
    assert result["kategorie"] == "Sonstiges", f"Erwartet Sonstiges, got {result['kategorie']}"
    assert result["konfidenz"] == 0.0, f"Erwartet 0.0, got {result['konfidenz']}"
    assert isinstance(result["tags"], list), "tags muss eine Liste sein"


# ---------------------------------------------------------------------------
# TEST 4: DuplicateChecker – SQLite anlegen und Duplikat erkennen
# ---------------------------------------------------------------------------

@test("DuplicateChecker: SQLite anlegen und Duplikat erkennen")
def _():
    sys.path.insert(0, str(Path(__file__).parent))
    from duplicate_check import DuplicateChecker
    import logging
    import sqlite3

    logger = logging.getLogger("test")
    db_path = Path(tempfile.gettempdir()) / "smoke_test_hashes.db"
    db_path.unlink(missing_ok=True)

    try:
        checker = DuplicateChecker(db_path, logger)

        # Noch kein Duplikat
        is_dup, original = checker.is_duplicate("abc123")
        assert not is_dup, "Neuer Hash faelschlich als Duplikat erkannt"

        # Registrieren
        checker.register_document("abc123", "test.pdf", "42")

        # Jetzt Duplikat
        is_dup, original = checker.is_duplicate("abc123")
        assert is_dup, "Duplikat nicht erkannt nach Registrierung"
        assert original == "test.pdf", f"Originaldatei falsch: {original}"
    finally:
        # SQLite-Verbindung schliessen vor Cleanup
        try:
            db_path.unlink(missing_ok=True)
        except Exception:
            pass  # Auf Windows koennen Locks auftreten – ignorieren


# ---------------------------------------------------------------------------
# TEST 5: PaperlessAPI – ISO-Datumskonvertierung
# ---------------------------------------------------------------------------

@test("PaperlessAPI: Datumskonvertierung korrekt")
def _():
    sys.path.insert(0, str(Path(__file__).parent))
    from paperless_api import PaperlessAPI

    # Normales Datum
    result = PaperlessAPI._to_iso8601("2024-08-15")
    assert "2024-08-15" in result, f"Datum falsch: {result}"

    # Tag 00 -> 01
    result = PaperlessAPI._to_iso8601("2024-08-00")
    assert "2024-08-01" in result, f"Tag 00 nicht auf 01 gesetzt: {result}"

    # Monat 00 -> 01
    result = PaperlessAPI._to_iso8601("2024-00-00")
    assert "2024-01-01" in result, f"Monat 00 nicht auf 01 gesetzt: {result}"

    # Jahr 0000 -> ValueError erwartet
    try:
        PaperlessAPI._to_iso8601("0000-00-00")
        assert False, "Jahr 0000 haette ValueError ausloesen sollen"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# TEST 6: auto_consume – sanitize() Funktion
# ---------------------------------------------------------------------------

@test("auto_consume: sanitize() Umlaute und Leerzeichen")
def _():
    sys.path.insert(0, str(Path(__file__).parent))
    from auto_consume import sanitize

    result = sanitize("Mueller GmbH")
    assert "Mueller" in result, f"Got: {result}"
    assert " " not in result, f"Leerzeichen nicht entfernt: {result}"

    result_umlaut = sanitize("Bäckerei")
    assert "ä" not in result_umlaut, f"Umlaut nicht entfernt: {result_umlaut}"
    assert "ae" in result_umlaut, f"ä wurde nicht zu ae: {result_umlaut}"


# ---------------------------------------------------------------------------
# TEST 7: poll_new_docs – sicherer Abbruch bei fehlendem Config (Unix only)
# ---------------------------------------------------------------------------

@test("poll_new_docs: _run() sicherer Abbruch bei fehlendem Token", skip_on_windows=True)
def _():
    sys.path.insert(0, str(Path(__file__).parent))
    import poll_new_docs as pnd
    import io
    from contextlib import redirect_stderr

    original = pnd.load_config
    pnd.load_config = lambda: {}  # type: ignore

    buf = io.StringIO()
    try:
        with redirect_stderr(buf):
            pnd._run()
    except Exception as exc:
        assert False, f"_run() warf Exception statt sauber abzubrechen: {exc}"
    finally:
        pnd.load_config = original

    output = buf.getvalue().lower()
    assert "fehlt" in output or "abbruch" in output, \
        f"Erwartete Fehlermeldung nicht gefunden: {buf.getvalue()!r}"


# ---------------------------------------------------------------------------
# TEST 8: HANotifier – deaktiviert wenn Config fehlt
# ---------------------------------------------------------------------------

@test("HANotifier: sicher deaktiviert ohne Config")
def _():
    sys.path.insert(0, str(Path(__file__).parent))
    from ha_notify import HANotifier
    import logging

    logger = logging.getLogger("test")
    notifier = HANotifier({}, logger)
    assert not notifier.enabled, "Notifier sollte deaktiviert sein bei fehlendem Config"

    # Darf keinen Fehler werfen
    notifier.notify_success("Test-Titel", "Rechnung", 0.95)
    notifier.notify_warning("Test-Warnung")
    notifier.notify_duplicate("neu.pdf", "original.pdf")


# ---------------------------------------------------------------------------
# TEST 9: config.yaml Schema-Validierung
# ---------------------------------------------------------------------------

@test("config.yaml: anthropic_api_key und paperless_token sind str? (optional)")
def _():
    import yaml as _yaml
    cfg_path = Path(__file__).parent.parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = _yaml.safe_load(fh)

    schema = cfg.get("schema", {})
    assert schema.get("anthropic_api_key") == "str?", \
        f"anthropic_api_key sollte str? sein, ist: {schema.get('anthropic_api_key')}"
    assert schema.get("paperless_token") == "str?", \
        f"paperless_token sollte str? sein, ist: {schema.get('paperless_token')}"


# ---------------------------------------------------------------------------
# Ergebnis-Zusammenfassung
# ---------------------------------------------------------------------------

def main():
    # UTF-8 output fuer Windows Terminal
    if IS_WINDOWS:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print()
    print("=" * 62)
    print("  SMOKE TEST -- scanservjs-ai KI-Scripts")
    print("=" * 62)

    for status, name in results:
        prefix = "  "
        print(f"{prefix}{status}  {name}")

    print("=" * 62)
    failures = [r for r in results if r[0] == FAIL]
    skipped = [r for r in results if r[0] == SKIP]
    total = len(results)
    passed = total - len(failures) - len(skipped)

    print(f"\n  {passed}/{total - len(skipped)} Tests bestanden"
          + (f"  ({len(skipped)} uebersprungen)" if skipped else ""))

    if failures:
        print(f"\n  WARNUNG: {len(failures)} Fehler -- bitte beheben!")
        sys.exit(1)
    else:
        print("\n  Alle Tests bestanden -- Software stabil")
        sys.exit(0)


if __name__ == "__main__":
    main()
