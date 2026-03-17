"""
Claude API Wrapper und Prompt-Logik fuer Dokumentenklassifikation

Modell  : claude-sonnet-4-6
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

SYSTEM_PROMPT = """\
Du bist ein Dokumenten-Klassifizierer fuer ein deutsches Haushaltsverwaltungssystem.

## Bekannte Stammdaten
Personen  : Wiesbrock (Christian, Maike), Schiefer, Hollmann
Orte      : Oerlinghausen, Helpup, Nedderhof, Detmold, Bielefeld
Firmen    : Bauhaus, Shell, BKK, Sparkasse Lemgo, Riverty, Amazon,
            Finanzamt Detmold, Klinikum Bielefeld, Hausarzt Beckmann

## Pflicht-Tags je Dokumenttyp
- Lohn / Lohnsteuer              -> Tags MUSS [Sparkasse] enthalten
- Kranken- / Sozialversicherung  -> Tags MUSS [Versicherung] enthalten
- Rezepte                        -> Tags MUSS [Rezepte] enthalten
- Haus-Bauakten (Hollmann)       -> Tags MUSS [Hollmann] UND [Helpup] enthalten

## Erlaubte Kategorien (exakt eine davon auswaehlen)
Haus | Arzt | Finanzamt | Krankenkasse | Lohnsteuer | Lohn |
Sozialversicherung | Rechnung | Arbeit | Sonstiges

## Regeln fuer Beschreibung und Tags
- Datum aus Dokumentinhalt extrahieren; bei Unklarheit: "0000-00-00"
  Partielle Daten sind erlaubt: "2024-01-00" (Monat bekannt, Tag nicht)
- Keine Umlaute: ae oe ue ss (z.B. Umsatzsteuer statt Umsatzsteuer)
- Keine Leerzeichen; Woerter mit Bindestrich trennen
- Beschreibung: praegnant, 2-5 Woerter, auf Deutsch
- Tags: Personen, Firmen, Orte, Jahre, Themen - maximal 10
- Kein generisches "Scan" als Tag oder in der Beschreibung
- Bevorzuge bekannte Stammdaten (s.o.) fuer Tags/Person/Firma

## Referenzbeispiele fuer korrekte Klassifikationen
Eingabe: Lohnabrechnung Maike Wiesbrock, Bauhaus GmbH, Januar 2024
Ausgabe:
{
  "datum": "2024-01-00",
  "kategorie": "Lohn",
  "beschreibung": "Bauhaus-Verdienstabrechnung-Januar-2024",
  "tags": ["Lohn","Bauhaus","Maike-Wiesbrock","2024","Sparkasse","Sparkasse-Lemgo","Oerlinghausen"],
  "person": "Maike Wiesbrock",
  "firma": "Bauhaus",
  "konfidenz": 0.97
}

Eingabe: BKK Krankengeld-Bescheinigung Ende AU 01.03.2025
Ausgabe:
{
  "datum": "2025-03-01",
  "kategorie": "Krankenkasse",
  "beschreibung": "BKK-Krankengeld-Ende-AU",
  "tags": ["Krankenkasse","Versicherung","BKK","Krankengeld","AU-Ende","Wiesbrock"],
  "person": "Wiesbrock",
  "firma": "BKK",
  "konfidenz": 0.95
}

Eingabe: Umsatzsteuer-Jahresbescheid Finanzamt Detmold, Wiesbrock GbR, 2023
Ausgabe:
{
  "datum": "2024-08-13",
  "kategorie": "Finanzamt",
  "beschreibung": "Detmold-Umsatzsteuer-Abrechnung-2023",
  "tags": ["Finanzamt","Detmold","Umsatzsteuer","2023","Wiesbrock-GbR","Oerlinghausen"],
  "person": "Wiesbrock",
  "firma": "Finanzamt Detmold",
  "konfidenz": 0.95
}

Antworte **ausschliesslich** mit validem JSON-Objekt.
Kein Markdown, keine Code-Blocks, kein erklaerende Text darum herum.\
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
        """Klassifiziert ein Dokument anhand von OCR-Text.

        Versucht bis zu 2 Mal (2. Versuch mit vereinfachtem Prompt).
        Gibt bei Dauerfehler FALLBACK_RESULT zurueck.
        """
        for attempt in range(1, 3):
            simplified = (attempt == 2)
            try:
                result = self._call_claude(ocr_text, simplified=simplified)
                self.logger.debug(f"Claude OK (Versuch {attempt}): {result}")
                return result

            except (json.JSONDecodeError, ValueError) as exc:
                self.logger.warning(
                    f"Ungueltiges JSON von Claude (Versuch {attempt}): {exc}"
                )
                if attempt == 1:
                    time.sleep(1)

            except anthropic.APITimeoutError:
                self.logger.error("Claude API Timeout (30 s) – verwende Fallback-Namen")
                break

            except anthropic.APIStatusError as exc:
                self.logger.error(f"Claude API Status-Fehler {exc.status_code}: {exc.message}")
                break

            except anthropic.APIError as exc:
                self.logger.error(f"Claude API Fehler: {exc} – verwende Fallback-Namen")
                break

        return FALLBACK_RESULT.copy()

    def _call_claude(self, ocr_text: str, simplified: bool = False) -> dict:
        """Fuehrt einen einzelnen API-Call durch und gibt das geparste Ergebnis zurueck."""
        if simplified:
            user_content = (
                f"Klassifiziere dieses Dokument. Antworte NUR mit einem JSON-Objekt.\n"
                f"Erlaubte Kategorien: {', '.join(KATEGORIEN)}\n\n"
                f"Pflichtfelder: datum, kategorie, beschreibung, tags, person, firma, konfidenz\n\n"
                f"Dokumenttext:\n{ocr_text}"
            )
        else:
            user_content = ocr_text

        message = self.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=512,
            timeout=30.0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        raw: str = message.content[0].text.strip()

        # Codeblock-Wrapper entfernen falls Claude ihn doch setzt
        code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        json_str = code_match.group(1) if code_match else raw

        # Ersten vollstaendigen JSON-Block extrahieren
        brace_match = re.search(r"\{.*\}", json_str, re.DOTALL)
        if not brace_match:
            raise json.JSONDecodeError("Kein JSON-Block in Antwort gefunden", json_str, 0)

        parsed: dict = json.loads(brace_match.group())
        self._normalize(parsed)
        return parsed

    def _normalize(self, result: dict) -> None:
        """Validiert und normalisiert das Claude-Ergebnis in-place."""
        # Kategorie auf Whitelist beschraenken
        if result.get("kategorie") not in KATEGORIEN:
            self.logger.warning(
                f"Unbekannte Kategorie {result.get('kategorie')!r} -> Sonstiges"
            )
            result["kategorie"] = "Sonstiges"

        # Tags sicherstellen
        if not isinstance(result.get("tags"), list):
            result["tags"] = []
        result["tags"] = [str(t) for t in result["tags"] if t][:10]

        # Konfidenz als float sicherstellen
        try:
            result["konfidenz"] = float(result.get("konfidenz") or 0.5)
        except (TypeError, ValueError):
            result["konfidenz"] = 0.5

        # Fehlende Felder mit Defaults fuellen
        result.setdefault("datum", "0000-00-00")
        result.setdefault("beschreibung", "Unbekannt")
        result.setdefault("person", None)
        result.setdefault("firma", None)
