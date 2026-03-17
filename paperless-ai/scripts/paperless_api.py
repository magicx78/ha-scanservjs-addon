"""
Paperless-ngx REST API Wrapper

Unterstuetzte Operationen:
  - Dokument-Volltext (OCR) abrufen
  - Titel, Korrespondent, Dokumenttyp, Tags und Datum aktualisieren
  - Tags / Korrespondenten / Dokumenttypen anlegen falls nicht vorhanden
  - Einzelnen Tag zu einem Dokument hinzufuegen (additiv)
"""

import logging
from typing import Optional

import requests


class PaperlessAPI:
    def __init__(self, config: dict, logger: logging.Logger) -> None:
        base = config["paperless_url"].rstrip("/")
        self.api_base = f"{base}/api"
        self.logger = logger

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {config['paperless_token']}",
                "Content-Type": "application/json",
            }
        )

    # -----------------------------------------------------------------------
    # Lesen
    # -----------------------------------------------------------------------

    def get_document_content(self, doc_id: str) -> str:
        """Gibt den OCR-Volltext des Dokuments zurueck (Feld 'content')."""
        try:
            resp = self.session.get(
                f"{self.api_base}/documents/{doc_id}/", timeout=15
            )
            resp.raise_for_status()
            return resp.json().get("content") or ""
        except requests.RequestException as exc:
            self.logger.error(f"Fehler beim Abrufen von Dokument {doc_id}: {exc}")
            return ""

    # -----------------------------------------------------------------------
    # Schreiben
    # -----------------------------------------------------------------------

    def update_document(
        self,
        doc_id: str,
        title: str,
        correspondent: Optional[str],
        document_type: Optional[str],
        tags: list,
        created: Optional[str],
    ) -> bool:
        """Aktualisiert Metadaten eines Dokuments via PATCH."""
        payload: dict = {"title": title}

        if created and created not in ("0000-00-00", ""):
            try:
                payload["created"] = self._to_iso8601(created)
            except ValueError as exc:
                self.logger.warning(f"Datum {created!r} konnte nicht konvertiert werden: {exc}")

        if correspondent:
            cid = self.get_or_create_correspondent(correspondent)
            if cid:
                payload["correspondent"] = cid

        if document_type:
            did = self.get_or_create_document_type(document_type)
            if did:
                payload["document_type"] = did

        if tags:
            tag_ids = [self.get_or_create_tag(t) for t in tags if t]
            payload["tags"] = [tid for tid in tag_ids if tid is not None]

        try:
            resp = self.session.patch(
                f"{self.api_base}/documents/{doc_id}/",
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            self.logger.info(f"Dokument {doc_id} aktualisiert | title={title!r}")
            return True
        except requests.RequestException as exc:
            body = getattr(exc.response, "text", "") if hasattr(exc, "response") else ""
            self.logger.error(f"Fehler beim Aktualisieren von Dokument {doc_id}: {exc} | Response: {body}")
            return False

    def add_tag(self, doc_id: str, tag_name: str) -> bool:
        """Fuegt einen einzelnen Tag additiv zu einem Dokument hinzu."""
        try:
            resp = self.session.get(
                f"{self.api_base}/documents/{doc_id}/", timeout=15
            )
            resp.raise_for_status()
            current_tags: list = resp.json().get("tags") or []

            tag_id = self.get_or_create_tag(tag_name)
            if tag_id is None:
                return False

            if tag_id not in current_tags:
                current_tags.append(tag_id)
                resp2 = self.session.patch(
                    f"{self.api_base}/documents/{doc_id}/",
                    json={"tags": current_tags},
                    timeout=15,
                )
                resp2.raise_for_status()
                self.logger.info(f"Tag {tag_name!r} zu Dokument {doc_id} hinzugefuegt")
            return True
        except requests.RequestException as exc:
            self.logger.error(
                f"Fehler beim Hinzufuegen von Tag {tag_name!r} zu Dokument {doc_id}: {exc}"
            )
            return False

    # -----------------------------------------------------------------------
    # Ressourcen anlegen / nachschlagen
    # -----------------------------------------------------------------------

    def get_or_create_tag(self, name: str) -> Optional[int]:
        return self._get_or_create("tags", name)

    def get_or_create_correspondent(self, name: str) -> Optional[int]:
        return self._get_or_create("correspondents", name)

    def get_or_create_document_type(self, name: str) -> Optional[int]:
        return self._get_or_create("document_types", name)

    def _get_or_create(self, resource: str, name: str) -> Optional[int]:
        """Sucht ein Objekt per Name (case-insensitive) oder legt es an."""
        try:
            resp = self.session.get(
                f"{self.api_base}/{resource}/",
                params={"name__iexact": name},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results") or []
            if results:
                return int(results[0]["id"])

            # Nicht gefunden -> anlegen
            resp2 = self.session.post(
                f"{self.api_base}/{resource}/",
                json={"name": name},
                timeout=15,
            )
            resp2.raise_for_status()
            created_id = int(resp2.json()["id"])
            self.logger.info(f"Neues {resource[:-1]} angelegt: {name!r} (id={created_id})")
            return created_id

        except requests.RequestException as exc:
            self.logger.error(
                f"Fehler bei get_or_create {resource}/{name!r}: {exc}"
            )
            return None

    # -----------------------------------------------------------------------
    # Hilfsmethoden
    # -----------------------------------------------------------------------

    @staticmethod
    def _to_iso8601(date_str: str) -> str:
        """Konvertiert JJJJ-MM-TT (Partialangaben erlaubt) zu ISO 8601.

        "0000-00-00"  -> ValueError
        "2024-08-00"  -> "2024-08-01T00:00:00+00:00"  (Tag 00 -> 01)
        "2024-00-00"  -> "2024-01-01T00:00:00+00:00"  (Monat 00 -> 01)
        """
        parts = date_str.split("-")
        if len(parts) != 3:
            raise ValueError(f"Unerwartetes Datumsformat: {date_str!r}")

        year, month, day = parts

        if year == "0000":
            raise ValueError(f"Jahr 0000 nicht zulassig: {date_str!r}")

        month = month if month not in ("00", "0", "") else "01"
        day = day if day not in ("00", "0", "") else "01"

        return f"{year}-{month.zfill(2)}-{day.zfill(2)}T00:00:00+00:00"
