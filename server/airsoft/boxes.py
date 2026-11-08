"""Turn box MQTT messages (status / state / heartbeat) into box state."""
import json
import time

from . import connmon, hub


def touch(ntype, nid):
    key = f"{ntype}/{nid}"
    n = hub.nodes.get(key)
    if n is None:
        n = {"type": ntype, "id": nid, "owner": "none", "red_s": 0,
             "blue_s": 0, "status": "online", "rssi": None, "ip": None,
             "arrival": time.time(),
             # connection stats for the current round (reset on Start)
             "drops": 0, "reboots": 0, "down_s": 0.0,
             "down_since": None, "down_reason": None, "last_live": None}
        hub.nodes[key] = n
    n["last_seen"] = time.time()
    return n


def on_message(client, userdata, msg):
    # The dashboard is the author of airsoft/game/* — ignore those on the way in.
    parts = msg.topic.split("/")
    if len(parts) < 4 or parts[0] != "airsoft" or parts[1] == "game":
        return
    ntype, nid, kind = parts[1], parts[2], parts[3]
    # Only messages a box itself publishes may create/refresh its tile. The
    # dashboard's own per-box topics (e.g. the retained .../rush role it writes)
    # echo back to us too; treating those as box traffic made alpha/bravo/charlie
    # appear "online" at startup even when powered off.
    if kind not in ("status", "state", "heartbeat"):
        return
    payload = msg.payload.decode("utf-8", "ignore").strip()
    # Retained messages are the broker replaying a box's LAST message (e.g. when
    # the dashboard starts) — they say nothing about whether it is alive now.
    live = not msg.retain
    now = time.time()

    with hub.nodes_lock:
        n = touch(ntype, nid)
        if kind == "status" and payload == "offline":
            if live and n.get("down_since") is None:
                connmon.mark_down(n, "offline", now)
                connmon.log(n, "offline", "dropped off MQTT (last will)")
        elif live:
            connmon.mark_up(n, now)
            n["last_live"] = now
        if kind == "status":
            n["status"] = payload or "online"
        elif kind in ("state", "heartbeat"):
            try:
                d = json.loads(payload)
            except ValueError:
                d = {}
            if live and kind == "heartbeat" and isinstance(d.get("uptime_s"), int):
                prev_up = n.get("uptime_s")
                if prev_up is not None and d["uptime_s"] < prev_up:
                    n["reboots"] = n.get("reboots", 0) + 1
                    connmon.log(n, "reboot", f"uptime {prev_up} s -> {d['uptime_s']} s")
                n["uptime_s"] = d["uptime_s"]
            if live and isinstance(d.get("rssi"), int):
                if d["rssi"] < connmon.CONN_WEAK_DBM and not n.get("weak"):
                    n["weak"] = True
                    n["rssi"] = d["rssi"]
                    connmon.log(n, "weak", f"signal {d['rssi']} dBm")
                elif d["rssi"] >= connmon.CONN_OK_DBM and n.get("weak"):
                    n["weak"] = False
                    n["rssi"] = d["rssi"]
                    connmon.log(n, "signal ok", f"signal {d['rssi']} dBm")
            prev = (n.get("owner"), n.get("red_s"), n.get("blue_s"))
            for f in ("owner", "red_s", "blue_s", "ip", "rssi"):
                if f in d:
                    n[f] = d[f]
            # Worst WiFi signal seen since the round started (reset on Start),
            # so referees can spot a box that dips when players crowd it.
            if isinstance(d.get("rssi"), int):
                lo = n.get("rssi_min")
                n["rssi_min"] = d["rssi"] if lo is None else min(lo, d["rssi"])
            # When owner/times change, restart the extrapolation clock (the Rush
            # arm timer, like the UI, ticks base + elapsed-since-this-moment).
            if (n.get("owner"), n.get("red_s"), n.get("blue_s")) != prev:
                n["arrival"] = time.time()
            if kind == "state" and ("owner" in d or "red_s" in d):
                n["updated"] = time.time()
            if kind == "heartbeat":
                n["status"] = "online"
        snapshot = dict(n)
    hub.broadcast(snapshot)
