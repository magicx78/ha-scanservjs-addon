"""
Claude API Wrapper und Prompt-Logik fuer Dokumentenklassifikation

Zwei separate API-Calls:
  1. Tags-Kontext  : extrahiert Tags, Person, Firma, Konfidenz
  2. Dateinamen-Kontext: extrahiert Datum, Kategorie, Beschreibung

Modell  : claude-haiku-4-5-20251001
Timeout : 30 s
Retries : 1 Retry mit vereinfachtem Prompt bei ungueltiger JSON-Antwort
"""

import json
import logging
import re
import time
from typing import Optional

import anthropic

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
           Finanzamt Detmold, Klinikum Bielefeld, Hausarzt Beckmann

## Pflicht-Tags je Dokumenttyp
- Lohn / Lohnsteuer             -> Tags MUSS [Sparkasse] enthalten
- Kranken- / Sozialversicherung -> Tags MUSS [Versicherung] enthalten
- Rezepte                       -> Tags MUSS [Rezepte] enthalten
- Haus-Bauakten (Hollmann)      -> Tags MUSS [Hollmann] UND [Helpup] enthalten

## Regeln
- Keine Umlaute: ae oe ue ss
- Keine Leerzeichen; Woerter mit Bindestrich trennen
- Tags: Personen, Firmen, Orte, Jahre, Themen – maximal 10
- Kein generisches "Scan" als Tag
- Bevorzuge bekannte Stammdaten fuer Tags/Person/Firma

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

## Regeln
- Datum aus Dokumentinhalt extrahieren; bei Unklarheit: "0000-00-00"
  Partielle Daten erlaubt: "2024-01-00" (Monat bekannt, Tag nicht)
- Keine Umlaute: ae oe ue ss
- Keine Leerzeichen; Woerter mit Bindestrich trennen
- Beschreibung: praegnant, 2-5 Woerter, auf Deutsch
- Kein generisches "Scan" in der Beschreibung

## Referenzbeispiele
Lohnabrechnung Maike Wiesbrock, Bauhaus, Januar 2024:
{"datum":"2024-01-00","kategorie":"Lohn","beschreibung":"Bauhaus-Verdienstabrechnung-Januar-2024"}

BKK Krankengeld-Bescheinigung 01.03.2025:
{"datum":"2025-03-01","kategorie":"Krankenkasse","beschreibung":"BKK-Krankengeld-Ende-AU"}

Antworte ausschliesslich mit validem JSON:
{
  "datum": "JJJJ-MM-TT",
  "kategorie": "...",
  "beschreibung": "..."
}
Kein Markdown, keine Code-Blocks.\
"""

FALLBACK_RESULT: dict = {
    "datum": "0000-00-00",
    "kategorie": "Sonstiges",
    "beschreibung": "Unbekannt",
    "tags": ["Pruefen"],
    "person": None,
    "firma": None,
    "konfidenz": 0.0,
}


# ---------------------------------------------------------------------------
# ClaudeNamer
# ---------------------------------------------------------------------------

class ClaudeNamer:
    def __init__(self, config: dict, logger: logging.Logger) -> None:
        self.logger = logger
        self.client = anthropic.Anthropic(api_key=config["anthropic_api_key"])

    def classify(self, ocr_text: str) -> dict:
        """Klassifiziert ein Dokument mit zwei separaten Claude-Calls.

        Call 1: Tags, Person, Firma, Konfidenz
        Call 2: Datum, Kategorie, Beschreibung
        Gibt bei Dauerfehler FALLBACK_RESULT zurueck.
        """
        tags_result = self._call_with_retry(
            ocr_text, SYSTEM_PROMPT_TAGS, ["tags", "person", "firma", "konfidenz"],
            context="Tags"
        )
        filename_result = self._call_with_retry(
            ocr_text, SYSTEM_PROMPT_FILENAME, ["datum", "kategorie", "beschreibung"],
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
