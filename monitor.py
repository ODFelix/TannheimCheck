"""
Startplatz-Monitor: 17. RAD-MARATHON Tannheimer Tal 2027 – 214-km-Strecke
==========================================================================

Fragt den JSON-Endpunkt ab, den die RaceResult-Anmeldeseite selbst lädt:
    https://my.raceresult.com/413749/registration/config?lang=de
Dort steht pro Anmeldeformular das Feld "SlotsLeft" (freie Plätze).
Stand 29.10.2026: "214KM Einzel-Anmeldung" -> SlotsLeft = 0 (ausgebucht).

Sobald SlotsLeft > 0 wird, kommt ein ntfy-Push mit höchster Priorität.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

EVENT_ID = os.environ.get("EVENT_ID", "413749")
FORM_NAME = os.environ.get("FORM_NAME", "214KM Einzel-Anmeldung")
CONFIG_URL = f"https://my.raceresult.com/{EVENT_ID}/registration/config?lang=de&test=&sanitize=true"
REG_URL = f"https://my.raceresult.com/{EVENT_ID}/registration"

NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
STATE_FILE = Path(os.environ.get("STATE_FILE", "state.json"))
ERROR_ALERT_AFTER = int(os.environ.get("ERROR_ALERT_AFTER", "3"))


def notify(title: str, message: str, priority: int = 3, tags: list[str] | None = None) -> None:
    """ntfy-Push per JSON (Umlaute/Emoji im Titel funktionieren so zuverlässig)."""
    print(f"[ntfy p{priority}] {title} | {message}")
    if not NTFY_TOPIC:
        print("NTFY_TOPIC nicht gesetzt – kein Push.")
        return
    r = requests.post(
        NTFY_SERVER,
        json={
            "topic": NTFY_TOPIC,
            "title": title,
            "message": message,
            "priority": priority,
            "tags": tags or [],
            "click": REG_URL,
            "actions": [{"action": "view", "label": "Jetzt anmelden", "url": REG_URL}],
        },
        timeout=15,
    )
    r.raise_for_status()


def fetch_form() -> dict:
    r = requests.get(
        CONFIG_URL,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (startplatz-monitor; 1 Abruf/5 min)"},
    )
    r.raise_for_status()
    data = r.json()
    for reg in data.get("Registrations") or []:
        if reg.get("Name") == FORM_NAME:
            return reg
    names = [reg.get("Name") for reg in data.get("Registrations") or []]
    raise LookupError(f"Formular '{FORM_NAME}' nicht gefunden. Vorhanden: {names}")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    state = load_state()
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    try:
        form = fetch_form()
    except Exception as exc:
        state["errors_in_row"] = state.get("errors_in_row", 0) + 1
        print(f"Fehler ({state['errors_in_row']}x in Folge): {exc}")
        if state["errors_in_row"] == ERROR_ALERT_AFTER:
            notify("Monitor: Abruf schlägt fehl",
                   f"{ERROR_ALERT_AFTER}x in Folge: {exc}", priority=3, tags=["warning"])
        save_state(state)
        return 0

    state["errors_in_row"] = 0
    slots = int(form.get("SlotsLeft", 0))
    prev = state.get("slots")
    print(f"{now}: {FORM_NAME} -> SlotsLeft={slots} (vorher {prev})")

    if prev is None:
        notify("Monitor aktiv ✅",
               f"214 km: aktuell {slots} freie Plätze. Du bekommst einen Push, sobald sich das ändert.",
               priority=2, tags=["eyes"])
    elif slots > 0 and slots != prev:
        notify(f"🚴 {slots} {'Startplatz' if slots == 1 else 'Startplätze'} frei – 214 km!",
               f"Freie Plätze: {prev} → {slots}. Schnell anmelden!",
               priority=5, tags=["rotating_light"])
    elif slots == 0 and prev and prev > 0:
        notify("214 km wieder ausgebucht",
               f"Freie Plätze: {prev} → 0.", priority=3, tags=["no_entry"])
    else:
        print("Keine relevante Änderung.")

    state["slots"] = slots          # bewusst ohne Zeitstempel: Commit nur bei echter Änderung
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
