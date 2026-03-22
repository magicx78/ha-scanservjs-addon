"""
Home Assistant REST API – Benachrichtigungen & Automation-Trigger

Konfiguration (config.yaml):
  ha_url                      : http://homeassistant.local:8123
  ha_token                    : <Long-Lived Access Token>
  ha_notify_target            : notify.mobile_app_iphone   (Domain.ServiceName)
  ha_automation_entity_id     : automation.datenfresser_trigger (optional)

Wenn ha_url oder ha_token fehlen, werden Benachrichtigungen still uebersprungen.
Automation-Trigger nur wenn ha_automation_entity_id gesetzt.
"""

import logging

import requests


class HANotifier:
    def __init__(self, config: dict, logger: logging.Logger) -> None:
        self.logger = logger
        self.enabled = bool(config.get("ha_url") and config.get("ha_token"))
        self.automation_entity_id = config.get("ha_automation_entity_id", "")

        if not self.enabled:
            self.logger.warning(
                "HA-Benachrichtigungen deaktiviert "
                "(ha_url oder ha_token fehlen in config.yaml)"
            )
            self.notify_url = ""
            self.automation_url = ""
            return

        ha_url = config["ha_url"].rstrip("/")
        target: str = config.get("ha_notify_target", "notify.persistent_notification")

        # Target-Format: "notify.mobile_app_iphone"  -> domain=notify, service=mobile_app_iphone
        # oder einfach  : "mobile_app_iphone"        -> domain=notify, service=mobile_app_iphone
        parts = target.split(".", 1)
        if len(parts) == 2:
            domain, service = parts
        else:
            domain, service = "notify", parts[0]

        self.notify_url = f"{ha_url}/api/services/{domain}/{service}"
        self.automation_url = f"{ha_url}/api/services/automation/trigger"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config['ha_token']}",
                "Content-Type": "application/json",
            }
        )

    # -----------------------------------------------------------------------
    # Oeffentliche Benachrichtigungs-Methoden
    # -----------------------------------------------------------------------

    def notify_success(self, title: str, kategorie: str, konfidenz: float) -> None:
        """Erfolgsmeldung nach erfolgreicher Klassifikation."""
        self._send(
            title="Neues Dokument klassifiziert",
            message=f"Kategorie: {kategorie} | Konfidenz: {konfidenz:.0%}\n{title}",
        )

    def notify_warning(self, message: str) -> None:
        """Warnung bei niedriger Konfidenz oder fehlendem OCR-Text."""
        self._send(
            title="Dokument pruefen",
            message=message,
        )

    def notify_duplicate(self, filename: str, original: str) -> None:
        """Duplikat-Meldung mit beiden Dateinamen."""
        self._send(
            title="Duplikat erkannt",
            message=f"Neu: {filename}\nOriginal: {original}",
        )

    def trigger_automation(self) -> None:
        """Triggert eine HA Automation (z.B. für Datenfresser-Ereignis)."""
        if not self.enabled or not self.automation_entity_id:
            return
        try:
            resp = self.session.post(
                self.automation_url,
                json={"entity_id": self.automation_entity_id},
                timeout=10,
            )
            resp.raise_for_status()
            self.logger.debug(f"HA-Automation getrggert: {self.automation_entity_id!r}")
        except requests.RequestException as exc:
            self.logger.warning(f"HA-Automation Trigger fehlgeschlagen: {exc}")

    # -----------------------------------------------------------------------
    # Interne Helfer
    # -----------------------------------------------------------------------

    def _send(self, title: str, message: str) -> None:
        if not self.enabled:
            return
        try:
            resp = self.session.post(
                self.notify_url,
                json={"title": title, "message": message},
                timeout=10,
            )
            resp.raise_for_status()
            self.logger.debug(f"HA-Benachrichtigung gesendet: {title!r}")
        except requests.RequestException as exc:
            # Fehler hier darf den Hauptfluss nicht unterbrechen
            self.logger.warning(f"HA-Benachrichtigung fehlgeschlagen: {exc}")
