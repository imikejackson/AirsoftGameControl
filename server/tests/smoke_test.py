#!/usr/bin/env python3
"""End-to-end smoke test for the dashboard server.

Drives a RUNNING dashboard + broker the way boxes and referee phones do: fake
boxes publish over MQTT, the referee logs in with the PIN and sends commands.
Run it before and after server changes; every check should pass both times.

    python server/tests/smoke_test.py [--url http://127.0.0.1:8080]
                                      [--broker localhost] [--pin-file server/ref_pin.txt]
                                      [--full]

--full adds the slow checks (a 30 s "silent" drop). Uses fake box ids "zt1" and
"zt2", plus "alpha" for Rush (whose bomb order is fixed), so run it against a
bench broker, NEVER the field server during a game. Restart the dashboard
afterwards to clear the fake tiles.
"""
import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import paho.mqtt.client as mqtt

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8080")
ap.add_argument("--broker", default="localhost")
ap.add_argument("--pin-file", default="server/ref_pin.txt")
ap.add_argument("--full", action="store_true")
args = ap.parse_args()
B = args.url.rstrip("/")
PIN = open(args.pin_file).read().strip()

failures = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def req(o, path, data=None, form=None):
    body, headers = None, {}
    if data is not None:
        body, headers = json.dumps(data).encode(), {"Content-Type": "application/json"}
    elif form is not None:
        body = urllib.parse.urlencode(form).encode()
    try:
        r = o.open(urllib.request.Request(B + path, data=body, headers=headers), timeout=10)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


anon, ref = opener(), opener()


def cmd(body):
    return req(ref, "/api/command", data=body)


# Collect everything the dashboard streams over SSE, in the background.
events = []


def sse_reader():
    r = urllib.request.urlopen(B + "/events", timeout=600)
    buf = b""
    while True:
        chunk = r.read1(65536)
        if not chunk:
            return
        buf += chunk
        *lines, buf = buf.split(b"\n")
        for line in lines:
            if line.startswith(b"data: "):
                events.append(json.loads(line[6:]))


def last(pred):
    for e in reversed(events):
        if pred(e):
            return e
    return None


def game():
    return last(lambda e: e.get("kind") == "game")


def tile(nid):
    return last(lambda e: e.get("id") == nid and "type" in e)


import threading  # noqa: E402

threading.Thread(target=sse_reader, daemon=True).start()

retained = {}
mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mq.on_message = lambda c, u, m: retained.__setitem__(m.topic, m.payload.decode())
mq.connect(args.broker, 1883, 30)
mq.subscribe([("airsoft/game/state", 0), ("airsoft/controlpoint/+/rush", 0)])
mq.loop_start()


def box(nid, kind, payload):
    mq.publish(f"airsoft/controlpoint/{nid}/{kind}",
               payload if isinstance(payload, str) else json.dumps(payload))


time.sleep(1.5)

print("pages and access control")
st, h = req(anon, "/")
check("player page loads", st == 200 and 'class="player"' in h)
check("player page shows a dash version", "dash v" in h)
st, h = req(anon, "/ref")
check("/ref without login shows the PIN page", "Enter the 6-digit PIN" in h)
check("command without login is refused", req(anon, "/api/command", data={"scope": "game", "action": "stop"})[0] == 403)
check("connection log without login is refused", req(anon, "/api/connlog")[0] == 403)
st, h = req(ref, "/ref", form={"pin": PIN})
check("PIN login reaches the referee page", 'class="ref"' in h)
check("command with login works", cmd({"scope": "game", "action": "stop"})[0] == 200)
check("bad catch-up level rejected", cmd({"scope": "game", "action": "setcatchup", "level": "silly"})[0] == 400)
check("bad mode rejected", cmd({"scope": "game", "action": "setmode", "mode": "silly"})[0] == 400)

print("domination scoring")
cmd({"scope": "game", "action": "setmode", "mode": "domination"})
cmd({"scope": "game", "action": "setcatchup", "level": "medium"})
for nid in ("zt1", "zt2"):
    box(nid, "status", "online")
    box(nid, "heartbeat", {"uptime_s": 100, "rssi": -55, "ip": "10.9.9.9"})
cmd({"scope": "game", "action": "start", "minutes": 2})
time.sleep(0.5)
for nid in ("zt1", "zt2"):
    box(nid, "state", {"owner": "red", "red_s": 0, "blue_s": 0})
t0 = time.time()
while time.time() - t0 < 10.5:
    time.sleep(3)
    for nid in ("zt1", "zt2"):
        box(nid, "heartbeat", {"uptime_s": 100 + int(time.time() - t0), "rssi": -55, "ip": "10.9.9.9"})
g = game()
check("game running", g and g["running"])
check("2 red boxes score 24/min", g and g["dom"]["red_ppm"] == 24.0, g and g["dom"])
check("score after ~10 s is 3..5", g and 3 <= g["dom"]["red"] <= 5, g and g["dom"]["red"])
gs = json.loads(retained.get("airsoft/game/state", "{}"))
check("boxes get score_red in game/state", "score_red" in gs, gs)
check("catch-up change mid-round", cmd({"scope": "game", "action": "setcatchup", "level": "high"})[0] == 200)
time.sleep(0.6)
check("catch-up level published", game()["catchup"] == "high")
cmd({"scope": "game", "action": "setcatchup", "level": "medium"})

print("connection monitoring")
box("zt1", "heartbeat", {"uptime_s": 5, "rssi": -55, "ip": "10.9.9.9"})        # reboot
box("zt1", "heartbeat", {"uptime_s": 17, "rssi": -80, "ip": "10.9.9.9"})       # weak
box("zt1", "heartbeat", {"uptime_s": 29, "rssi": -72, "ip": "10.9.9.9"})       # still weak
box("zt1", "heartbeat", {"uptime_s": 41, "rssi": -65, "ip": "10.9.9.9"})       # ok
box("zt1", "status", "offline")                                                # last will
time.sleep(1)
box("zt1", "status", "online")                                                 # back
time.sleep(1.5)
log = json.loads(req(ref, "/api/connlog")[1])
evs = [e["event"] for e in log if e["node"] == "zt1"]
check("reboot logged", "reboot" in evs, evs)
check("weak then ok logged once each", evs.count("weak") == 1 and evs.count("signal ok") == 1, evs)
check("offline then back logged", "offline" in evs and "back" in evs, evs)
t = tile("zt1")
check("tile counts 1 drop, 1 reboot", t and t.get("drops") == 1 and t.get("reboots") == 1,
      t and {k: t.get(k) for k in ("drops", "reboots")})
check("tile carries rssi_min", t and t.get("rssi_min") == -80, t and t.get("rssi_min"))
if args.full:
    print("  (waiting 35 s for a silent drop)")
    time.sleep(35)
    log = json.loads(req(ref, "/api/connlog")[1])
    check("silent logged after 30 s", any(e["node"] == "zt2" and e["event"] == "silent" for e in log))
cmd({"scope": "game", "action": "start", "minutes": 2})
time.sleep(1)
t = tile("zt1")
check("Start resets per-round counters", t and t.get("drops") == 0 and t.get("reboots") == 0)
log = json.loads(req(ref, "/api/connlog")[1])
check("Start logs a round marker", log and log[-1]["event"] == "round")
check("Start zeroes scores", game()["dom"]["red"] == 0)
cmd({"scope": "game", "action": "stop"})

print("rush")
check("mode change to rush", cmd({"scope": "game", "action": "setmode", "mode": "rush"})[0] == 200)
cmd({"scope": "game", "action": "setattacker", "team": "red"})
check("defuse clamps to 0..5", cmd({"scope": "game", "action": "setdefuse", "seconds": 9})[0] == 200)
time.sleep(0.5)
check("defuse stored as 5", game()["defuse_s"] == 5, game()["defuse_s"])
cmd({"scope": "game", "action": "start", "minutes": 5})
box("alpha", "status", "online")
time.sleep(0.5)
box("alpha", "state", {"owner": "red", "red_s": 0, "blue_s": 0})
time.sleep(4.5)
g = game()
check("rush round set up", g.get("rush") is not None and g["rush"]["active"] == 1, g.get("rush"))
check("attacker on bomb 1 arms it", g.get("rush") and g["rush"]["arm_s"] >= 3, g.get("rush"))
gs = json.loads(retained.get("airsoft/game/state", "{}"))
check("boxes get arm_s/fuse_s", gs.get("fuse_s") == 60 and "arm_s" in gs, gs)
check("alpha's role is active", retained.get("airsoft/controlpoint/alpha/rush") == "active")
check("bravo's role is pending", retained.get("airsoft/controlpoint/bravo/rush") == "pending")
cmd({"scope": "game", "action": "stop"})
time.sleep(0.6)
check("stopped rush unlocks boxes", retained.get("airsoft/controlpoint/bravo/rush") == "off")
cmd({"scope": "game", "action": "setmode", "mode": "domination"})
cmd({"scope": "game", "action": "setdefuse", "seconds": 0})
box("alpha", "status", "offline")

print("tiles")
check("dashboard's own rush topics don't create tiles", tile("bravo") is None)

print()
print(f"{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
