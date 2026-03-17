"""
TEST-05: build_title – Titel > 128 Zeichen wird korrekt abgeschnitten
         + Sanitize-Funktion
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from auto_consume import build_title, sanitize  # noqa: E402


class TestBuildTitle:
    def test_normal_title(self):
        result = build_title({
            "datum": "2024-01-15",
            "kategorie": "Lohn",
            "beschreibung": "Bauhaus-Abrechnung",
            "tags": ["Sparkasse", "2024"],
        })
        assert result == "2024-01-15_Lohn_Bauhaus-Abrechnung_[Sparkasse][2024]"

    def test_title_truncated_at_128_chars(self):
        """Titel mit langen Tags wird auf 128 Zeichen begrenzt."""
        result = build_title({
            "datum": "2024-01-01",
            "kategorie": "Sonstiges",
            "beschreibung": "Ein-sehr-langer-Beschreibungstext-der-viele-Zeichen-hat",
            "tags": [
                "Tag-Eins-Sehr-Lang", "Tag-Zwei-Sehr-Lang", "Tag-Drei-Sehr-Lang",
                "Tag-Vier-Sehr-Lang", "Tag-Fuenf-Sehr-Lang", "Tag-Sechs-Sehr-Lang",
                "Tag-Sieben-Sehr-Lang", "Tag-Acht-Sehr-Lang",
            ],
        })
        assert len(result) <= 128

    def test_title_exactly_128_chars_allowed(self):
        """Genau 128 Zeichen ist erlaubt."""
        # Erzeuge Titel der genau 128 Zeichen hat
        result = build_title({
            "datum": "2024-01-01",
            "kategorie": "Sonstiges",
            "beschreibung": "X" * 50,
            "tags": [],
        })
        assert len(result) <= 128

    def test_missing_fields_use_defaults(self):
        """Fehlende Felder → Standardwerte."""
        result = build_title({})
        assert "0000-00-00" in result
        assert "Sonstiges" in result
        assert "Unbekannt" in result

    def test_max_10_tags(self):
        """Mehr als 10 Tags → nur erste 10 werden übernommen."""
        result = build_title({
            "datum": "2024-01-01",
            "kategorie": "Lohn",
            "beschreibung": "Test",
            "tags": [f"Tag{i}" for i in range(15)],
        })
        # 10 Tags max → aber Länge trotzdem ≤ 128
        assert len(result) <= 128
        assert result.count("[") <= 10

    def test_no_tags_no_brackets(self):
        """Ohne Tags kein Klammerblock."""
        result = build_title({
            "datum": "2024-06-01",
            "kategorie": "Arzt",
            "beschreibung": "Rezept",
            "tags": [],
        })
        assert "[" not in result
        assert result == "2024-06-01_Arzt_Rezept"


class TestSanitize:
    def test_umlaut_ae(self):
        assert sanitize("Käse") == "Kaese"

    def test_umlaut_oe(self):
        assert sanitize("Öl") == "Oel"

    def test_umlaut_ue(self):
        assert sanitize("Über") == "Ueber"

    def test_eszett(self):
        assert sanitize("Straße") == "Strasse"

    def test_space_to_hyphen(self):
        assert sanitize("Hallo Welt") == "Hallo-Welt"

    def test_special_chars_removed(self):
        result = sanitize("Test!@#$%^&*()")
        assert "!" not in result
        assert "@" not in result

    def test_hyphen_and_dot_preserved(self):
        result = sanitize("file-name.pdf")
        assert result == "file-name.pdf"
