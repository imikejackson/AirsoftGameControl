"""Referee settings that survive a dashboard restart (speaker on/off, which
callouts and reminders play, ...), stored as JSON in state/settings.json
(gitignored: it's per-server runtime data)."""
import json
import os
import threading

from . import config

STATE_DIR = os.path.join(config.SERVER_DIR, "state")
SETTINGS_FILE = os.path.join(STATE_DIR, "settings.json")
_lock = threading.Lock()


def load():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save(section, value):
    """Replace one top-level section (e.g. "audio", "announcer") and write."""
    with _lock:
        data = load()
        data[section] = value
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
