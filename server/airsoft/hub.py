"""Shared runtime state: boxes, the game, live browsers, and the MQTT client.

Lock order: never take nodes_lock while holding game_lock (the clock and the
modes read box state first, then update the game).
"""
import json
import queue
import threading

from . import config

nodes = {}                  # "type/id" -> node dict
nodes_lock = threading.Lock()
_subs = []                  # list[queue.Queue] for SSE clients
_subs_lock = threading.Lock()
client = None               # the paho client, for publishing (set by bridge)

# Authoritative game clock + mode (this server owns it). Each mode keeps its
# own keys here too (see modes/*.py): e.g. "dom" for Domination, "rush" for Rush.
game = {"running": False, "remaining_s": float(config.DEFAULT_DURATION_S),
        "duration_s": config.DEFAULT_DURATION_S, "mode": "domination"}
game_lock = threading.Lock()


def subscribe():
    """A new live browser: returns its queue."""
    q = queue.Queue(maxsize=200)
    with _subs_lock:
        _subs.append(q)
    return q


def unsubscribe(q):
    with _subs_lock:
        _subs.remove(q)


def broadcast(obj):
    """Send one JSON object to every live browser."""
    data = json.dumps(obj)
    with _subs_lock:
        for q in list(_subs):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def publish(topic, payload, retain=False):
    if client is not None:
        client.publish(topic, payload, qos=1, retain=retain)


def game_payload():
    """The game state sent to browsers (base fields plus every mode's extras)."""
    from . import modes
    with game_lock:
        p = {"kind": "game", "running": game["running"],
             "remaining_s": int(round(game["remaining_s"])),
             "duration_s": game["duration_s"], "mode": game["mode"]}
        for m in modes.ALL:
            p.update(m.payload(game))
        return p


def publish_game():
    """Push the game clock to the broker (retained, authoritative) and the UI."""
    from . import modes
    p = game_payload()
    node = {"running": p["running"], "remaining_s": p["remaining_s"],
            "duration_s": p["duration_s"], "mode": p["mode"]}
    node.update(modes.current(p["mode"]).node_fields(p))
    publish("airsoft/game/state", json.dumps(node), retain=True)
    broadcast(p)
