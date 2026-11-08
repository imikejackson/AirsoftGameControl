"""Connection monitoring: does each box stay connected?

Makes a flaky box (bad antenna spot, weak power) show up as data instead of a
hunch. Events go to the referee page live and are appended to
logs/connections.log (survives restarts).
  offline  broker delivered the box's Last Will (it dropped off MQTT)
  silent   no message from the box for CONN_SILENT_S (heartbeat is ~12 s)
  back     the box is heard from again after offline/silent (+ downtime)
  reboot   the box's uptime counter went backwards (power blip / crash)
  weak / signal ok   RSSI crossed below CONN_WEAK_DBM / back above CONN_OK_DBM
"""
import os
import time
from collections import deque
from datetime import datetime

from . import config, hub

CONN_SILENT_S = 30
CONN_WEAK_DBM = -75
CONN_OK_DBM = -70             # hysteresis so a borderline box doesn't spam the log
CONN_LOG_DIR = os.path.join(config.SERVER_DIR, "logs")
CONN_LOG_FILE = os.path.join(CONN_LOG_DIR, "connections.log")
recent = deque(maxlen=300)    # recent events for the referee page


def log(n, event, detail=""):
    """Record a connection event: in memory, on disk, and live to referees.
    Called with hub.nodes_lock held (n is a node dict) or n=None for markers."""
    now = time.time()
    e = {"t": now, "node": (n["id"] if n else "-"), "event": event, "detail": detail,
         "rssi": (n.get("rssi") if n else None)}
    recent.append(e)
    try:
        os.makedirs(CONN_LOG_DIR, exist_ok=True)
        with open(CONN_LOG_FILE, "a") as f:
            stamp = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{stamp}  {e['node']:<10} {event:<10} {detail}"
                    f"{'  rssi ' + str(e['rssi']) if e['rssi'] is not None else ''}\n")
    except OSError as err:
        print(f"[dash] can't write {CONN_LOG_FILE}: {err}")
    print(f"[conn] {e['node']} {event} {detail}")
    hub.broadcast({"kind": "connlog", **e})


def mark_down(n, reason, now):
    if n.get("down_since") is None:
        n["down_since"], n["down_reason"] = now, reason
        n["drops"] = n.get("drops", 0) + 1


def mark_up(n, now):
    since = n.get("down_since")
    if since is not None:
        gone = now - since
        n["down_s"] = n.get("down_s", 0.0) + gone
        n["down_since"] = n["down_reason"] = None
        log(n, "back", f"after {int(gone)} s")


def watchdog(now):
    """A box heard from recently that has gone quiet for CONN_SILENT_S counts
    as dropped (catches WiFi loss before the broker's Last Will fires, and
    boxes with no LWT at all). Called from the clock loop."""
    stale = []
    with hub.nodes_lock:
        for n in hub.nodes.values():
            ll = n.get("last_live")
            if ll is not None and n.get("down_since") is None and now - ll > CONN_SILENT_S:
                mark_down(n, "silent", ll)   # count the downtime from last contact
                log(n, "silent", f"no message for {int(now - ll)} s")
                stale.append(dict(n))
    for snap in stale:
        hub.broadcast(snap)


def new_round():
    """Start of a round: fresh signal + connection stats on every box, sent to
    the browsers right away (otherwise a tile shows last round's counts until
    that box next checks in, or forever if it's offline)."""
    now = time.time()
    with hub.nodes_lock:
        for n in hub.nodes.values():
            n["rssi_min"] = n.get("rssi")
            n["drops"], n["reboots"], n["down_s"] = 0, 0, 0.0
            if n.get("down_since") is not None:
                n["down_since"] = now   # still down: count from round start
        log(None, "round", "started — counters reset")
        snaps = [dict(n) for n in hub.nodes.values()]
    for snap in snaps:
        hub.broadcast(snap)
