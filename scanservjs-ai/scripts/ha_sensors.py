#!/usr/bin/env python3
"""
Home Assistant Sensor-Updates fuer den Datenfresser

Liest /data/datenfresser-status.json und pusht Sensor-States an die HA REST API.
Wird als Daemon gestartet und aktualisiert alle 60 Sekunden.

Sensoren:
  sensor.datenfresser_inbox_count       - Dateien in Inbox
  sensor.datenfresser_error_count       - Dateien in errors/
  sensor.datenfresser_duplicate_count   - Dateien in duplicates/
  sensor.datenfresser_unsupported_count - Dateien in unsupported/
  sensor.datenfresser_last_document     - Letztes verarbeitetes Dokument
  binary_sensor.datenfresser_running    - Prozess laeuft
"""

import json
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

SCRIPT_DIR = Path(__file__).parent
STATUS_FILE = Path("/data/datenfresser-status.json")
SENSOR_PREFIX = "datenfresser"
UPDATE_INTERVAL = 60  # Sekunden


def load_config() -> dict:
    """Laedt Config aus /opt/paperless-ai/config.yaml + Env-Variablen.

    Prioritaet: Env-Var > config.yaml
    Im Addon-Container ist SUPERVISOR_TOKEN automatisch gesetzt.
    """
    cfg_path = SCRIPT_DIR / "config.yaml"  # /opt/paperless-ai/config.yaml
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        cfg = {}
    # Env-Variablen ueberschreiben config.yaml (Supervisor setzt SUPERVISOR_TOKEN)
    for key, env_var in (
        ("ha_url", "HA_URL"),
        ("ha_token", "HA_TOKEN"),
        ("ha_token", "SUPERVISOR_TOKEN"),
    ):
        val = os.environ.get(env_var)
        if val:
            cfg[key] = val
    # Im Addon-Container: Supervisor-URL verwenden wenn kein ha_url gesetzt
    if not cfg.get("ha_url") and os.environ.get("SUPERVISOR_TOKEN"):
        cfg["ha_url"] = "http://supervisor/core"
    return cfg


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("ha_sensors")
    logger.setLevel(logging.INFO)

    fh = logging.handlers.RotatingFileHandler(
        Path("/data/ha_sensors.log"),
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
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


def read_status() -> dict:
    """Liest die Status-Datei vom Datenfresser."""
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def post_sensor(
    session: requests.Session,
    ha_url: str,
    entity_id: str,
    state: str,
    attributes: dict,
    logger: logging.Logger,
) -> bool:
    """Setzt einen Sensor-State in Home Assistant via REST API."""
    url = f"{ha_url}/api/states/{entity_id}"
    payload = {"state": str(state), "attributes": attributes}
    try:
        resp = session.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.warning(f"Sensor {entity_id} Update fehlgeschlagen: {exc}")
        return False


def update_sensors(session: requests.Session, ha_url: str, status: dict, logger: logging.Logger) -> None:
    """Aktualisiert alle Datenfresser-Sensoren in HA."""
    updated = status.get("updated", "")

    # sensor.datenfresser_inbox_count
    post_sensor(session, ha_url, f"sensor.{SENSOR_PREFIX}_inbox_count", status.get("inbox_count", 0), {
        "friendly_name": "Datenfresser Inbox",
        "icon": "mdi:inbox-arrow-down",
        "unit_of_measurement": "Dateien",
        "updated": updated,
    }, logger)

    # sensor.datenfresser_error_count
    post_sensor(session, ha_url, f"sensor.{SENSOR_PREFIX}_error_count", status.get("error_count", 0), {
        "friendly_name": "Datenfresser Fehler",
        "icon": "mdi:alert-circle",
        "unit_of_measurement": "Dateien",
        "error_path": "/share/datenfresser/errors",
        "updated": updated,
    }, logger)

    # sensor.datenfresser_duplicate_count
    post_sensor(session, ha_url, f"sensor.{SENSOR_PREFIX}_duplicate_count", status.get("duplicate_count", 0), {
        "friendly_name": "Datenfresser Duplikate",
        "icon": "mdi:content-duplicate",
        "unit_of_measurement": "Dateien",
        "duplicate_path": "/share/datenfresser/duplicates",
        "updated": updated,
    }, logger)

    # sensor.datenfresser_unsupported_count
    post_sensor(session, ha_url, f"sensor.{SENSOR_PREFIX}_unsupported_count", status.get("unsupported_count", 0), {
        "friendly_name": "Datenfresser Inkompatibel",
        "icon": "mdi:file-alert",
        "unit_of_measurement": "Dateien",
        "unsupported_path": "/share/datenfresser/unsupported",
        "updated": updated,
    }, logger)

    # sensor.datenfresser_last_document
    last_doc = status.get("last_document", "")
    last_error = status.get("last_error", "")
    post_sensor(session, ha_url, f"sensor.{SENSOR_PREFIX}_last_document", last_doc or "Keine", {
        "friendly_name": "Datenfresser Letztes Dokument",
        "icon": "mdi:file-document-check",
        "last_error": last_error,
        "updated": updated,
    }, logger)

    # binary_sensor.datenfresser_running
    running = status.get("running", False)
    # Prüfe ob Status-Datei nicht zu alt ist (> 5 Minuten = vermutlich tot)
    if updated:
        try:
            status_time = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - status_time).total_seconds()
            if age_seconds > 300:
                running = False
        except (ValueError, TypeError):
            pass

    post_sensor(session, ha_url, f"binary_sensor.{SENSOR_PREFIX}_running", "on" if running else "off", {
        "friendly_name": "Datenfresser Aktiv",
        "icon": "mdi:cog-sync" if running else "mdi:cog-off",
        "device_class": "running",
        "updated": updated,
    }, logger)


def main() -> None:
    logger = setup_logging()
    config = load_config()

    ha_url = (config.get("ha_url") or "").rstrip("/")
    ha_token = config.get("ha_token") or ""

    if not ha_url or not ha_token:
        logger.error("ha_url oder ha_token fehlt – HA-Sensoren deaktiviert")
        return

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    })

    logger.info(f"HA-Sensor-Daemon gestartet | ha_url={ha_url} | intervall={UPDATE_INTERVAL}s")

    while True:
        try:
            status = read_status()
            if status:
                update_sensors(session, ha_url, status, logger)
            else:
                # Kein Status vorhanden – sende "offline" Sensoren
                update_sensors(session, ha_url, {"running": False}, logger)
        except Exception as exc:
            logger.error(f"Sensor-Update fehlgeschlagen: {exc}", exc_info=True)

        try:
            time.sleep(UPDATE_INTERVAL)
        except KeyboardInterrupt:
            logger.info("HA-Sensor-Daemon beendet")
            break


if __name__ == "__main__":
    main()
