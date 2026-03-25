"""
Claude API Wrapper und Prompt-Logik fuer Dokumentenklassifikation

Zwei separate API-Calls:
  1. Tags-Kontext  : extrahiert Tags, Person, Firma, Konfidenz
  2. Dateinamen-Kontext: extrahiert Datum, Kategorie, Beschreibung

Caching:
  - MD5-Hash des OCR-Textes als Cache-Key
  - SQLite Basis + optional Redis
  - 24h TTL Standard

Modell  : claude-haiku-4-5-20251001
Timeout : 30 s
Retries : 1 Retry mit vereinfachtem Prompt bei ungueltiger JSON-Antwort
"""

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import anthropic

SCRIPT_DIR = Path(__file__).parent

try:
    from cache_manager import HybridCache  # noqa: E402
except ImportError:
    HybridCache = None

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

KATEGORIEN = [
    "Haus", "Arzt", "Finanzamt", "Krankenkasse", "Lohnsteuer",
    "Lohn", "Sozialversicherung", "Rechnung", "Arbeit", "Sonstiges",
]

# --- Kontext 1: Tags --------------------------------------------------------
SYSTEM_PROMPT_TAGS = """\
Du extrahierst Tags, Personen und Firmen aus einem deutschen Haushaltsdokument.

## Bekannte Stammdaten
Personen : Wiesbrock (Christian, Maike), Schiefer, Hollmann
Orte     : Oerlinghausen, Helpup, Nedderhof, Detmold, Bielefeld
Firmen   : Bauhaus, Shell, BKK, Sparkasse Lemgo, Riverty, Amazon,
           Finanzamt Detmold, Klinikum Bielefeld, Hausarzt Beckmann,
           Telekom, Vodafone, E.ON, Stadtwerke Bielefeld, ADAC

## Pflicht-Tags je Dokumenttyp
- Lohn / Lohnsteuer             -> Tags MUSS [Sparkasse] enthalten
- Kranken- / Sozialversicherung -> Tags MUSS [Versicherung] enthalten
- Rezepte                       -> Tags MUSS [Rezepte] enthalten
- Haus-Bauakten (Hollmann)      -> Tags MUSS [Hollmann] UND [Helpup] enthalten
- Rechnungen / Mahnungen        -> Tags MUSS Firmenname enthalten
- Steuer / Finanzamt            -> Tags MUSS [Steuer] UND Jahr enthalten
- Versicherungen (nicht KK)     -> Tags MUSS [Versicherung] UND Versicherer enthalten
- Arbeitsvertrag / Kuendigung   -> Tags MUSS [Arbeit] UND Arbeitgeber enthalten

## Regeln
- Keine Umlaute: ae oe ue ss
- Keine Leerzeichen; Woerter mit Bindestrich trennen
- Tags: Personen, Firmen, Orte, Jahre, Themen – maximal 10
- Kein generisches "Scan", "Dokument", "Seite" oder "Brief" als Tag
- Bevorzuge bekannte Stammdaten fuer Tags/Person/Firma
- Bei Rechnungen: Rechnungsnummer NICHT als Tag verwenden
- Jahreszahl als Tag nur wenn im Dokument erkennbar (z.B. "2024")
- person = die Person an die das Dokument gerichtet ist (Empfaenger)
- firma = der Absender / ausstellende Organisation

## Referenzbeispiele
Lohnabrechnung Bauhaus fuer Maike Wiesbrock, Januar 2024:
{"tags":["Bauhaus","Wiesbrock","Lohn","2024","Sparkasse"],"person":"Maike Wiesbrock","firma":"Bauhaus","konfidenz":0.95}

BKK Krankengeld-Bescheinigung fuer Christian Wiesbrock:
{"tags":["BKK","Wiesbrock","Versicherung","Krankengeld","2025"],"person":"Christian Wiesbrock","firma":"BKK","konfidenz":0.90}

Amazon Rechnung ueber USB-Kabel, 15.02.2025:
{"tags":["Amazon","Rechnung","2025","Online-Kauf"],"person":null,"firma":"Amazon","konfidenz":0.92}

Finanzamt Detmold Einkommensteuerbescheid 2023:
{"tags":["Finanzamt-Detmold","Steuer","Einkommensteuer","2023","Wiesbrock"],"person":"Christian Wiesbrock","firma":"Finanzamt Detmold","konfidenz":0.95}

FALSCH (zu generisch): {"tags":["Scan","Dokument","Brief"],...}
FALSCH (Rechnungsnr): {"tags":["INV-2024-00815"],...}

Antworte ausschliesslich mit validem JSON:
{
  "tags": ["Tag1", "Tag2"],
  "person": "Name oder null",
  "firma": "Firma oder null",
  "konfidenz": 0.95
}
Kein Markdown, keine Code-Blocks.\
"""

# --- Kontext 2: Dateiname ---------------------------------------------------
SYSTEM_PROMPT_FILENAME = """\
Du erzeugst strukturierte Metadaten fuer den Dateinamen eines deutschen Haushaltsdokuments.

## Erlaubte Kategorien (exakt eine auswaehlen)
Haus | Arzt | Finanzamt | Krankenkasse | Lohnsteuer | Lohn |
Sozialversicherung | Rechnung | Arbeit | Sonstiges

## Kategorie-Zuordnung (Entscheidungshilfe)
- Arztbrief, Befund, Rezept, Ueberweisung     -> Arzt
- Lohnabrechnung, Gehaltsnachweis              -> Lohn
- Lohnsteuerbescheinigung, Lohnsteuer-Jahres   -> Lohnsteuer
- Krankenkasse, Krankengeld, AU-Bescheinigung  -> Krankenkasse
- Rentenversicherung, Sozialvers.-Nachweis     -> Sozialversicherung
- Steuerbescheid, Finanzamt, EkSt, USt         -> Finanzamt
- Kaufvertrag, Grundbuch, Baugenehmigung       -> Haus
- Rechnung, Mahnung, Quittung, Bestellung      -> Rechnung
- Arbeitsvertrag, Kuendigung, Zeugnis          -> Arbeit
- Alles andere                                 -> Sonstiges

## Regeln
- Datum aus Dokumentinhalt extrahieren; bei Unklarheit: "0000-00-00"
  Partielle Daten erlaubt: "2024-01-00" (Monat bekannt, Tag nicht)
- Keine Umlaute: ae oe ue ss
- Keine Leerzeichen; Woerter mit Bindestrich trennen
- Beschreibung: praegnant, 2-5 Woerter, auf Deutsch
- Beschreibung MUSS den Absender/Firma enthalten
- Beschreibung MUSS den Dokumenttyp benennen (z.B. Rechnung, Bescheid, Abrechnung)
- Kein generisches "Scan", "Dokument" oder "Brief" in der Beschreibung

## Referenzbeispiele (8 Stueck)
Lohnabrechnung Maike Wiesbrock, Bauhaus, Januar 2024:
{"datum":"2024-01-00","kategorie":"Lohn","beschreibung":"Bauhaus-Verdienstabrechnung-Januar-2024"}

BKK Krankengeld-Bescheinigung 01.03.2025:
{"datum":"2025-03-01","kategorie":"Krankenkasse","beschreibung":"BKK-Krankengeld-Ende-AU"}

Amazon Rechnung USB-Kabel 15.02.2025:
{"datum":"2025-02-15","kategorie":"Rechnung","beschreibung":"Amazon-Rechnung-USB-Kabel"}

Finanzamt Detmold Einkommensteuerbescheid 2023:
{"datum":"2024-06-00","kategorie":"Finanzamt","beschreibung":"Finanzamt-Detmold-EkSt-Bescheid-2023"}

Hausarzt Beckmann Ueberweisung zum Radiologen:
{"datum":"2025-01-15","kategorie":"Arzt","beschreibung":"Beckmann-Ueberweisung-Radiologie"}

Sparkasse Lemgo Kontoauszug Maerz 2025:
{"datum":"2025-03-00","kategorie":"Rechnung","beschreibung":"Sparkasse-Lemgo-Kontoauszug-Maerz-2025"}

Arbeitsvertrag Bauhaus fuer Maike Wiesbrock:
{"datum":"2023-04-01","kategorie":"Arbeit","beschreibung":"Bauhaus-Arbeitsvertrag-Wiesbrock"}

Telekom Mobilfunk-Rechnung Februar 2025:
{"datum":"2025-02-00","kategorie":"Rechnung","beschreibung":"Telekom-Mobilfunk-Rechnung-Februar-2025"}

FALSCH (zu generisch): {"beschreibung":"Schreiben"} oder {"beschreibung":"Brief-vom-Amt"}
RICHTIG (spezifisch): {"beschreibung":"Finanzamt-Detmold-EkSt-Bescheid-2023"}

Antworte ausschliesslich mit validem JSON:
{
  "datum": "JJJJ-MM-TT",
  "kategorie": "...",
  "beschreibung": "..."
}
Kein Markdown, keine Code-Blocks.\
"""

def _load_prompt(file_path: str, fallback: str, extra_rules: str = "") -> str:
    """Laedt Prompt aus Datei, faellt auf Hardcoded-Default zurueck.

    Haengt optionale Zusatzregeln an.
    """
    prompt = fallback
    if file_path:
        p = Path(file_path)
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    prompt = content
            except OSError:
                pass  # Fallback verwenden

    if extra_rules and extra_rules.strip():
        prompt += f"\n\n## Zusaetzliche Regeln\n{extra_rules.strip()}"

    return prompt


FALLBACK_RESULT: dict = {
    "datum": "0000-00-00",
    "kategorie": "Sonstiges",
    "beschreibung": "Unbekannt",
    "tags": ["KI-Fehler"],
    "person": None,
    "firma": None,
    "konfidenz": 0.0,
}


# ---------------------------------------------------------------------------
# ClaudeNamer
# ---------------------------------------------------------------------------

class ClaudeNamer:
    def __init__(self, config: dict, logger: logging.Logger, redis_client=None) -> None:
        self.logger = logger
        self.client = anthropic.Anthropic(api_key=config["anthropic_api_key"])

        # Prompts laden (Datei > Hardcoded, plus optionale Config-Regeln)
        self.prompt_tags = _load_prompt(
            config.get("prompt_tags_file", ""),
            SYSTEM_PROMPT_TAGS,
            config.get("custom_tags_rules", ""),
        )
        self.prompt_filename = _load_prompt(
            config.get("prompt_filename_file", ""),
            SYSTEM_PROMPT_FILENAME,
            config.get("custom_filename_rules", ""),
        )
        tags_src = config.get("prompt_tags_file") or "builtin"
        fname_src = config.get("prompt_filename_file") or "builtin"
        self.logger.info(f"Prompts geladen: tags={tags_src}, filename={fname_src}")

        # Cache initialisieren
        self.cache = None
        if HybridCache:
            try:
                cache_db_path = Path(config.get("cache_db_path", "/data/cache_classifications.db"))
                cache_enabled = config.get("cache_enabled", True)
                if cache_enabled:
                    self.cache = HybridCache(cache_db_path, logger, redis_client=redis_client)
                    self.cache_ttl = int(config.get("cache_ttl_seconds", 86400))
                    self.logger.info(f"Classification-Cache aktiviert: {cache_db_path}")
            except Exception as exc:
                self.logger.warning(f"Cache-Initialisierung fehlgeschlagen: {exc}")

    def classify(self, ocr_text: str) -> dict:
        """Klassifiziert ein Dokument mit zwei separaten Claude-Calls.

        Call 1: Tags, Person, Firma, Konfidenz
        Call 2: Datum, Kategorie, Beschreibung
        Gibt bei Dauerfehler FALLBACK_RESULT zurueck.
        Nutzt Cache wenn konfiguriert.
        """
        # Cache-Check
        input_hash = hashlib.md5(ocr_text.encode()).hexdigest() if self.cache else None
        if self.cache:
            cached = self.cache.get(input_hash)
            if cached:
                return cached["result"]

        tags_result = self._call_with_retry(
            ocr_text, self.prompt_tags, ["tags", "person", "firma", "konfidenz"],
            context="Tags"
        )
        filename_result = self._call_with_retry(
            ocr_text, self.prompt_filename, ["datum", "kategorie", "beschreibung"],
            context="Dateiname"
        )

        if tags_result is None and filename_result is None:
            return FALLBACK_RESULT.copy()

        result = FALLBACK_RESULT.copy()
        if filename_result:
            result.update({k: filename_result[k] for k in ("datum", "kategorie", "beschreibung") if k in filename_result})
        if tags_result:
            result.update({k: tags_result[k] for k in ("tags", "person", "firma", "konfidenz") if k in tags_result})

        self._normalize(result)

        # Cache speichern
        if self.cache and input_hash:
            self.cache.set(input_hash, result, ttl_seconds=self.cache_ttl)

        return result

    def _call_with_retry(self, ocr_text: str, system_prompt: str, required_fields: list, context: str) -> Optional[dict]:
        """Fuehrt einen API-Call mit einem Retry durch."""
        for attempt in range(1, 3):
            try:
                result = self._call_claude(ocr_text, system_prompt)
                self.logger.debug(f"Claude {context} OK (Versuch {attempt}): {result}")
                return result
            except (json.JSONDecodeError, ValueError) as exc:
                self.logger.warning(f"Ungueltiges JSON von Claude {context} (Versuch {attempt}): {exc}")
                if attempt == 1:
                    time.sleep(1)
            except anthropic.APITimeoutError:
                self.logger.error(f"Claude API Timeout ({context}) – verwende Fallback")
                break
            except anthropic.APIStatusError as exc:
                self.logger.error(f"Claude API Status-Fehler {exc.status_code}: {exc.message}")
                break
            except anthropic.APIError as exc:
                self.logger.error(f"Claude API Fehler ({context}): {exc}")
                break
        return None

    def _call_claude(self, ocr_text: str, system_prompt: str) -> dict:
        """Fuehrt einen einzelnen API-Call durch und gibt das geparste Ergebnis zurueck."""
        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            timeout=30.0,
            system=system_prompt,
            messages=[{"role": "user", "content": ocr_text}],
        )

        raw: str = message.content[0].text.strip()

        code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        json_str = code_match.group(1) if code_match else raw

        brace_match = re.search(r"\{.*\}", json_str, re.DOTALL)
        if not brace_match:
            raise json.JSONDecodeError("Kein JSON-Block in Antwort gefunden", json_str, 0)

        return json.loads(brace_match.group())

    def _normalize(self, result: dict) -> None:
        """Validiert und normalisiert das Ergebnis in-place."""
        if result.get("kategorie") not in KATEGORIEN:
            self.logger.warning(f"Unbekannte Kategorie {result.get('kategorie')!r} -> Sonstiges")
            result["kategorie"] = "Sonstiges"

        if not isinstance(result.get("tags"), list):
            result["tags"] = []
        result["tags"] = [str(t) for t in result["tags"] if t][:10]

        try:
            result["konfidenz"] = float(result.get("konfidenz") or 0.5)
        except (TypeError, ValueError):
            result["konfidenz"] = 0.5

        result.setdefault("datum", "0000-00-00")
        result.setdefault("beschreibung", "Unbekannt")
        result.setdefault("person", None)
        result.setdefault("firma", None)
