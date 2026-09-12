#!/usr/bin/env python3
"""Airsoft Control Point — live web dashboard + game controls.

Subscribes to the MQTT broker, keeps live node state in memory, and serves a
self-updating scoreboard over Server-Sent Events. It is also the GAME-CLOCK
AUTHORITY: it owns the countdown, publishes the retained airsoft/game/state
(running + remaining_s) ~1x/s, and ends the round at zero. Single file: Flask +
paho-mqtt with all HTML/JS embedded. Nodes are auto-discovered.

Open http://<pi>:8080  (e.g. http://airsoft-pi.local:8080).
"""
import json
import os
import queue
import threading
import time

from flask import (Flask, Response, request, jsonify, abort,
                   send_from_directory, render_template_string)
import paho.mqtt.client as mqtt

SOUNDS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sounds")

DASH_VERSION = 11           # bump on every dashboard change; shown in the header
MQTT_HOST = "localhost"
MQTT_PORT = 1883
TOPIC = "airsoft/#"
HTTP_PORT = 8080
DEFAULT_DURATION_S = 15 * 60

# Friendly display names per node_id (mirrors NODE_LABELS in the firmware's
# config.h). node_id stays the identifier on the MQTT topics; this is just for
# display. A node_id not listed here falls back to showing its id.
NODE_LABELS = {"alpha": "Pink Hallway", "bravo": "Kill House", "charlie": "Dark Room"}

# --- Rush mode -------------------------------------------------------------
# Bombs are armed in sequence across these boxes. Arm progress on the active
# bomb = the attacking team's hold time on that box (paused while defenders hold
# it). When a bomb detonates, the next box is reset so its clock starts fresh.
RUSH_ORDER = [("controlpoint", "alpha"),    # bomb #1 = Pink Hallway
              ("controlpoint", "bravo"),    # bomb #2 = Kill House
              ("controlpoint", "charlie")]  # bomb #3 = Dark Room
RUSH_FUSES = [60, 120, 180]   # bomb #1/#2/#3 fuse seconds (1/2/3 min)
RUSH_DEFUSE_MAX = 5           # cap on the sudden-death defuse hold (s)

app = Flask(__name__)

_nodes = {}                 # "type/id" -> node dict
_nodes_lock = threading.Lock()
_subs = []                  # list[queue.Queue] for SSE clients
_subs_lock = threading.Lock()
_client = None              # the paho client, for publishing
_last_rush_pub = None       # dedup for the retained per-node rush status

# Authoritative game clock + mode (this server owns it).
#   mode      "domination" (KotH) | "rush"
#   attacker  "red" | "blue"  — the arming team in Rush (referee-set)
#   defuse_s  0..RUSH_DEFUSE_MAX — sudden-death defuse hold (referee-set)
#   rush      runtime state dict while a Rush round is set up, else None:
#             {active, detonated[3], arm_s, fuses[3], sudden_death,
#              defuse_hold_s, _defuse_start, result}
_game = {"running": False, "remaining_s": float(DEFAULT_DURATION_S),
         "duration_s": DEFAULT_DURATION_S, "mode": "domination",
         "attacker": "red", "defuse_s": 0, "rush": None}
_game_lock = threading.Lock()


def _broadcast(obj):
    data = json.dumps(obj)
    with _subs_lock:
        for q in list(_subs):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def _game_payload():
    with _game_lock:
        p = {"kind": "game", "running": _game["running"],
             "remaining_s": int(round(_game["remaining_s"])),
             "duration_s": _game["duration_s"], "mode": _game["mode"],
             "attacker": _game["attacker"], "defuse_s": _game["defuse_s"]}
        r = _game.get("rush")
        if r is not None:
            p["rush"] = {"active": r["active"], "detonated": list(r["detonated"]),
                         "arm_s": int(round(r["arm_s"])), "fuses": list(r["fuses"]),
                         "sudden_death": r["sudden_death"],
                         "defuse_hold_s": round(r["defuse_hold_s"], 1),
                         "result": r["result"]}
        return p


def _publish_game():
    """Push the game clock to the broker (retained, authoritative) and the UI."""
    p = _game_payload()
    node = {"running": p["running"], "remaining_s": p["remaining_s"],
            "duration_s": p["duration_s"], "mode": p["mode"]}
    r = p.get("rush")
    if p["mode"] == "rush" and r is not None:
        a = r["active"]
        node["attacker"] = p["attacker"]        # which team is arming
        node["arm_s"] = r["arm_s"]              # active bomb's arm progress (s)
        node["fuse_s"] = r["fuses"][a - 1] if 1 <= a <= 3 else 0
    if _client is not None:
        _client.publish("airsoft/game/state", json.dumps(node), qos=1, retain=True)
    _broadcast(p)


def _touch(ntype, nid):
    key = f"{ntype}/{nid}"
    n = _nodes.get(key)
    if n is None:
        n = {"type": ntype, "id": nid, "owner": "none", "red_s": 0,
             "blue_s": 0, "status": "online", "rssi": None, "ip": None,
             "arrival": time.time()}
        _nodes[key] = n
    n["last_seen"] = time.time()
    return n


def _on_connect(client, userdata, flags, rc, *args):
    print(f"[dash] connected to broker (rc={rc}); subscribing to {TOPIC}")
    client.subscribe(TOPIC)
    _publish_game()  # establish the current (idle) game state on the bus


def _on_message(client, userdata, msg):
    # The dashboard is the author of airsoft/game/* — ignore those on the way in.
    parts = msg.topic.split("/")
    if len(parts) < 4 or parts[0] != "airsoft" or parts[1] == "game":
        return
    ntype, nid, kind = parts[1], parts[2], parts[3]
    payload = msg.payload.decode("utf-8", "ignore").strip()

    with _nodes_lock:
        n = _touch(ntype, nid)
        if kind == "status":
            n["status"] = payload or "online"
        elif kind in ("state", "heartbeat"):
            try:
                d = json.loads(payload)
            except ValueError:
                d = {}
            prev = (n.get("owner"), n.get("red_s"), n.get("blue_s"))
            for f in ("owner", "red_s", "blue_s", "ip", "rssi"):
                if f in d:
                    n[f] = d[f]
            # When owner/times change, restart the extrapolation clock (the Rush
            # arm timer, like the UI, ticks base + elapsed-since-this-moment).
            if (n.get("owner"), n.get("red_s"), n.get("blue_s")) != prev:
                n["arrival"] = time.time()
            if kind == "state" and ("owner" in d or "red_s" in d):
                n["updated"] = time.time()
            if kind == "heartbeat":
                n["status"] = "online"
        snapshot = dict(n)
    _broadcast(snapshot)


def _mqtt_loop():
    global _client
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)  # paho 2.x
    except (AttributeError, TypeError):
        client = mqtt.Client()                                  # paho 1.x
    client.on_connect = _on_connect
    client.on_message = _on_message
    _client = client
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, 60)
            client.loop_forever()
        except Exception as e:  # noqa: BLE001 — keep the bridge alive
            print(f"[dash] mqtt error: {e}; retrying in 3s")
            time.sleep(3)


def _rush_owner(active):
    """Current owner ('red'/'blue'/'none') of the active bomb's box, or None."""
    if active < 1 or active > 3:
        return None
    ntype, nid = RUSH_ORDER[active - 1]
    with _nodes_lock:
        n = _nodes.get(f"{ntype}/{nid}")
        return (n.get("owner") if n else None)


def _publish_rush_status():
    """Publish each box's retained Rush role (off/pending/active/detonated) so it
    locks + shows the right thing. Only publishes when a role actually changes."""
    global _last_rush_pub
    with _game_lock:
        r = _game.get("rush")
        on = (_game["mode"] == "rush" and r is not None
              and _game["running"] and r["result"] is None)
        active = r["active"] if r else 0
        det = list(r["detonated"]) if r else [False, False, False]
    statuses = []
    for i in range(3):
        if not on:
            statuses.append("off")            # not a live Rush round -> unlocked
        elif det[i]:
            statuses.append("detonated")
        elif active == i + 1:
            statuses.append("active")
        else:
            statuses.append("pending")
    sig = tuple(statuses)
    if sig == _last_rush_pub:
        return
    _last_rush_pub = sig
    if _client is not None:
        for (ntype, nid), st in zip(RUSH_ORDER, statuses):
            _client.publish(f"airsoft/{ntype}/{nid}/rush", st, qos=1, retain=True)
        print(f"[dash] rush status -> {statuses}")


def _clock_loop():
    """Tick the countdown, run the Rush state machine, republish on change.

    Rush arm timer is accrued HERE (server-side) from box ownership: while the
    active bomb's box is owned by the attacker the timer advances; a defender
    holding it pauses the timer (attackers resume where they left off). This
    avoids depending on the node's own cumulative timers or resets.
    """
    last = time.time()
    last_pub = None
    while True:
        time.sleep(0.2)
        now = time.time()
        dt, last = now - last, now

        with _game_lock:
            g = _game
            r = g.get("rush")

            # 1) Countdown.
            if g["running"] and g["remaining_s"] > 0:
                g["remaining_s"] = max(0.0, g["remaining_s"] - dt)
                if g["remaining_s"] <= 0:
                    g["remaining_s"] = 0.0
                    if (g["mode"] == "rush" and r is not None and r["result"] is None
                            and r["active"] >= 3 and not r["detonated"][2]):
                        r["sudden_death"] = True      # bomb-3 race; keep running
                    else:
                        g["running"] = False
                        if g["mode"] == "rush" and r is not None and r["result"] is None:
                            r["result"] = "defenders"  # held them off to time

            attacker = g["attacker"]
            defender = "blue" if attacker == "red" else "red"
            mode, running = g["mode"], g["running"]
            defuse_target = float(g["defuse_s"])
            active = r["active"] if r else 0
            sudden = r["sudden_death"] if r else False
            rush_live = (mode == "rush" and r is not None and r["result"] is None)

        # 2) Rush arm / detonation / sudden-death defuse.
        if rush_live and 1 <= active <= 3:
            owner = _rush_owner(active)
            with _game_lock:
                r = _game["rush"]
                if r is not None and r["result"] is None and r["active"] == active:
                    if (running or sudden) and owner == attacker:
                        r["arm_s"] += dt                       # attackers arming
                    if r["arm_s"] >= r["fuses"][active - 1]:    # boom
                        r["detonated"][active - 1] = True
                        if active >= 3:
                            r["result"] = "attackers"
                            _game["running"] = False
                        else:
                            r["active"] = active + 1
                            r["arm_s"] = 0.0
                            r["_defuse_start"] = None
                    elif sudden and active == 3:               # defenders defuse
                        if owner == defender:
                            if r.get("_defuse_start") is None:
                                r["_defuse_start"] = now
                            r["defuse_hold_s"] = now - r["_defuse_start"]
                            if r["defuse_hold_s"] >= defuse_target:
                                r["result"] = "defenders"
                                _game["running"] = False
                        else:
                            r["_defuse_start"] = None
                            r["defuse_hold_s"] = 0.0

        # 3) Publish on any meaningful change.
        with _game_lock:
            r = _game.get("rush")
            cur = (int(round(_game["remaining_s"])), _game["running"], _game["mode"],
                   (r["active"] if r else None),
                   (int(round(r["arm_s"])) if r else None),
                   (r["sudden_death"] if r else None),
                   (r["result"] if r else None),
                   (int(r["defuse_hold_s"]) if r else None),
                   (tuple(r["detonated"]) if r else None))
        if cur != last_pub:
            last_pub = cur
            _publish_game()
        _publish_rush_status()   # retained per-box lock/role (deduped internally)


@app.route("/")
def index():
    resp = Response(render_template_string(INDEX_HTML, ver=DASH_VERSION,
                                           labels=json.dumps(NODE_LABELS)))
    resp.headers["Cache-Control"] = "no-store"  # always serve the latest page
    return resp


@app.route("/events")
def events():
    def stream():
        q = queue.Queue(maxsize=200)
        with _subs_lock:
            _subs.append(q)
        try:
            yield f"data: {json.dumps(_game_payload())}\n\n"
            with _nodes_lock:
                snap = [dict(n) for n in _nodes.values()]
            for n in snap:
                yield f"data: {json.dumps(n)}\n\n"
            while True:
                try:
                    yield f"data: {q.get(timeout=15)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _subs_lock:
                _subs.remove(q)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/packs")
def packs():
    """List voice packs (subdirs of sounds/) and the .mp3 clips in each."""
    out = {}
    try:
        for name in sorted(os.listdir(SOUNDS_DIR)):
            d = os.path.join(SOUNDS_DIR, name)
            if os.path.isdir(d):
                out[name] = sorted(f for f in os.listdir(d) if f.lower().endswith(".mp3"))
    except FileNotFoundError:
        pass
    return jsonify(out)


@app.route("/sounds/<pack>/<path:fname>")
def sound(pack, fname):
    if "/" in pack or pack.startswith("."):
        abort(404)
    return send_from_directory(os.path.join(SOUNDS_DIR, pack), fname)


@app.route("/api/command", methods=["POST"])
def command():
    if _client is None:
        return jsonify(ok=False, error="broker not connected"), 503
    body = request.get_json(force=True, silent=True) or {}
    scope = body.get("scope")
    action = body.get("action", "reset")

    if scope == "game":
        if action == "start":            # fresh round: reset scores + full clock
            with _game_lock:
                mins = float(body.get("minutes", _game["duration_s"] / 60))
                _game["duration_s"] = max(1, int(mins * 60))
                _game["remaining_s"] = float(_game["duration_s"])
                _game["running"] = True
                if _game["mode"] == "rush":
                    _game["rush"] = {"active": 1, "detonated": [False, False, False],
                                     "arm_s": 0.0, "fuses": list(RUSH_FUSES),
                                     "sudden_death": False, "defuse_hold_s": 0.0,
                                     "_defuse_start": None, "result": None}
                else:
                    _game["rush"] = None
            _client.publish("airsoft/game/command", "reset_all", qos=1, retain=False)
            _publish_game()
        elif action == "stop":           # freeze everything
            with _game_lock:
                _game["running"] = False
            _publish_game()
        elif action == "settime":        # set duration (and idle countdown)
            with _game_lock:
                mins = float(body.get("minutes", 15))
                _game["duration_s"] = max(1, int(mins * 60))
                if not _game["running"]:
                    _game["remaining_s"] = float(_game["duration_s"])
            _publish_game()
        elif action == "setmode":        # domination | rush (only when idle)
            m = body.get("mode", "domination")
            if m not in ("domination", "rush"):
                return jsonify(ok=False, error="bad mode"), 400
            with _game_lock:
                if not _game["running"]:
                    _game["mode"] = m
                    _game["rush"] = None
            _publish_game()
        elif action == "setattacker":    # rush: which team attacks
            t = body.get("team", "red")
            if t not in ("red", "blue"):
                return jsonify(ok=False, error="bad team"), 400
            with _game_lock:
                _game["attacker"] = t
            _publish_game()
        elif action == "setdefuse":      # rush: sudden-death defuse hold (0..MAX)
            try:
                s = int(body.get("seconds", 0))
            except (TypeError, ValueError):
                s = 0
            with _game_lock:
                _game["defuse_s"] = max(0, min(RUSH_DEFUSE_MAX, s))
            _publish_game()
        else:
            return jsonify(ok=False, error="bad action"), 400
        return jsonify(ok=True)

    if scope == "all":
        topic, payload = "airsoft/game/command", "reset_all"
    elif scope == "node":
        ntype, nid = body.get("type"), body.get("id")
        if not ntype or not nid:
            return jsonify(ok=False, error="missing type/id"), 400
        topic, payload = f"airsoft/{ntype}/{nid}/command", "reset"
    else:
        return jsonify(ok=False, error="bad scope"), 400

    _client.publish(topic, payload, qos=1, retain=False)
    print(f"[dash] command -> {topic} = {payload}")
    return jsonify(ok=True, topic=topic, payload=payload)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Airsoft Control Points</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, sans-serif; background:#0d0f12; color:#e8e8e8; }
  header { background:#15181d; border-bottom:1px solid #262b33; }
  header .bar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:10px 16px; }
  .bar-mode { border-top:1px solid #21262e; background:#12151a; }
  header h1 { font-size:18px; margin:0; font-weight:700; letter-spacing:.04em; }
  .modehint { font-size:13px; color:#7d8794; letter-spacing:.02em; }
  .bar-mode label.ctl { font-size:14px; color:#cdd3da; }
  #status { font-size:13px; color:#7d8794; }
  .ver { font-size:11px; color:#7d8794; letter-spacing:.05em; }
  .spacer { margin-left:auto; }
  #clock { font-size:34px; font-weight:800; font-variant-numeric: tabular-nums;
           letter-spacing:.02em; }
  #clock.low { color:#ff5c5c; } #clock.over { color:#ff5c5c; }
  #clock.idle { color:#7d8794; }
  .ctl { display:flex; align-items:center; gap:8px; }
  /* Touch-friendly controls (referees are usually on a phone): >=44px targets,
     16px text so iOS doesn't zoom on focus. */
  input#minutes { width:70px; font:inherit; font-size:16px; text-align:center; min-height:46px;
        background:#0d0f12; color:#e8e8e8; border:1px solid #3a414c; border-radius:9px; padding:8px; }
  select.sel { font:inherit; font-size:16px; min-height:46px; background:#0d0f12; color:#e8e8e8;
        border:1px solid #3a414c; border-radius:9px; padding:8px 12px; }
  button.btn { font:inherit; font-size:16px; font-weight:600; color:#e8e8e8; min-height:46px;
        background:#2a2f37; border:1px solid #3a414c; border-radius:9px;
        padding:10px 18px; cursor:pointer; }
  label.ctl { display:inline-flex; align-items:center; gap:8px; }
  button.btn:hover { background:#343a44; }
  button.btn.go { background:#1d6f33; border-color:#2a9648; }
  button.btn.go:hover { background:#23843d; }
  button.btn.danger { background:#7a1d24; border-color:#a32a33; }
  button.btn.danger:hover { background:#94242c; }
  #grid { display:grid; gap:14px; padding:18px;
          grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
  .tile { background:#171a1f; border:1px solid #262b33; border-radius:12px;
          overflow:hidden; transition:opacity .3s; }
  .tile.offline { opacity:.4; }
  .thead { display:flex; align-items:center; gap:8px; padding:10px 14px;
           border-bottom:1px solid #262b33; }
  .thead .name { font-size:20px; font-weight:700; letter-spacing:.05em; }
  .thead .type { font-size:11px; text-transform:uppercase; color:#7d8794; letter-spacing:.1em; }
  .dot { width:10px; height:10px; border-radius:50%; background:#3a4a3a; margin-left:auto; }
  .dot.on { background:#46d160; box-shadow:0 0 8px #46d16088; }
  .dot.off { background:#555; }
  .row { display:flex; align-items:center; justify-content:space-between;
         padding:10px 14px; font-variant-numeric: tabular-nums; }
  .row .lbl { font-weight:700; letter-spacing:.08em; }
  .row .t { font-size:30px; font-weight:700; font-variant-numeric: tabular-nums; }
  .row.red  { background:#2a1416; }  .row.red.own  { background:#c0212e; }
  .row.blue { background:#121a2e; }  .row.blue.own { background:#1f4fd0; }
  .row.own .t { color:#fff; }
  .foot { padding:8px 14px; font-size:12px; color:#7d8794; display:flex;
          align-items:center; justify-content:space-between; border-top:1px solid #262b33; }
  .foot .cap { color:#ffcf5c; font-weight:600; }
  button.reset { font:inherit; font-size:11px; color:#cdd3da; background:transparent;
        border:1px solid #3a414c; border-radius:6px; padding:3px 8px; cursor:pointer; }
  button.reset:hover { background:#2a2f37; }
  .empty { color:#7d8794; padding:40px; text-align:center; }
  #results { display:none; margin:14px 18px 0; padding:16px 20px; border-radius:12px;
        background:#15181d; border:1px solid #3a414c; }
  #results .rtitle { font-size:13px; letter-spacing:.22em; font-weight:800; color:#ffcf5c; }
  #results .rtable { border-collapse:collapse; margin-top:12px; }
  #results .rtable th, #results .rtable td { padding:8px 28px 8px 0; text-align:left;
        border-bottom:1px solid #262b33; white-space:nowrap; }
  #results .rtable th { font-size:11px; color:#7d8794; letter-spacing:.1em;
        text-transform:uppercase; font-weight:600; }
  #results .rtable td { font-size:24px; font-weight:800; font-variant-numeric:tabular-nums; }
  #results .rtable td.tm { font-size:16px; letter-spacing:.06em; }
  #results .r-red td { color:#ff6b6b; } #results .r-blue td { color:#6b9bff; }
  #results .rtable td.lead { text-decoration:underline; text-underline-offset:4px; }
  #results .rwin { margin-top:12px; font-size:22px; font-weight:800; letter-spacing:.04em; }
  #results .rwin .ww-red { color:#ff6b6b; } #results .rwin .ww-blue { color:#6b9bff; }
  /* Rush panel */
  #rushpanel { display:none; margin:14px 18px 0; padding:16px 20px; border-radius:12px;
        background:#15181d; border:1px solid #3a414c; }
  .rushtop { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:14px; }
  .rushtop .phase { font-size:13px; letter-spacing:.16em; font-weight:800; color:#ffcf5c; }
  .rushtop .sd { font-size:12px; letter-spacing:.14em; font-weight:800; color:#ff5c5c;
        border:1px solid #ff5c5c; border-radius:6px; padding:3px 8px; display:none; }
  .rushtop .rwin { margin-left:auto; font-size:20px; font-weight:800; letter-spacing:.03em; }
  .rushtop .rwin .win-red { color:#ff6b6b; } .rushtop .rwin .win-blue { color:#6b9bff; }
  .bombs { display:grid; gap:12px; grid-template-columns: repeat(3, 1fr); }
  @media (max-width:640px){ .bombs { grid-template-columns:1fr; } }
  .bomb { background:#12151a; border:1px solid #262b33; border-radius:10px; padding:12px 14px; }
  .bomb .bh { display:flex; align-items:baseline; gap:8px; }
  .bomb .bn { font-size:17px; font-weight:700; }
  .bomb .bf { font-size:12px; color:#7d8794; margin-left:auto; font-variant-numeric:tabular-nums; }
  .bomb .bs { font-size:11px; letter-spacing:.12em; font-weight:700; text-transform:uppercase;
        margin-top:3px; color:#7d8794; }
  .bomb.active .bs { color:#ffcf5c; } .bomb.done .bs { color:#ff5c5c; }
  .bomb .bar { height:12px; border-radius:6px; background:#0d0f12; border:1px solid #2a2f37;
        margin-top:10px; overflow:hidden; }
  .bomb .fill { height:100%; width:0; background:#555; transition:width .2s linear; }
  .bomb .fill.red { background:#c0212e; } .bomb .fill.blue { background:#1f4fd0; }
  .bomb .arm { margin-top:8px; font-variant-numeric:tabular-nums; line-height:1.1; min-height:36px;
        font-size:32px; font-weight:700; color:#e8e8e8; }
  .bomb .arm .tot { font-size:16px; font-weight:400; color:#9aa4b0; }
  .bomb .def { font-size:13px; color:#ffcf5c; margin-top:4px; min-height:15px;
        font-variant-numeric:tabular-nums; }
  .bomb.active { border-color:#ffcf5c55; } .bomb.done { border-color:#7a1d24; opacity:.9; }
</style>
</head>
<body>
<header>
  <!-- Row 1: primary game controls -->
  <div class="bar bar-primary">
    <h1>AIRSOFT</h1>
    <span class="ver">dash v{{ ver }}</span>
    <span id="status">connecting…</span>
    <span class="spacer"></span>
    <span id="clock" class="idle">--:--</span>
    <label class="ctl">Mode
      <select id="mode" class="sel" title="Game mode">
        <option value="domination">Domination</option>
        <option value="rush">Rush</option>
      </select></label>
    <label class="ctl"><input id="minutes" type="number" min="1" max="120" value="15"> min</label>
    <button class="btn go" id="startStop">Start</button>
    <button class="btn danger" id="resetAll">Reset All</button>
    <select id="pack" class="sel" title="Voice pack"><option value="">Browser voice</option></select>
    <button class="btn" id="audioBtn">🔇 Audio</button>
  </div>
  <!-- Row 2: options for the selected game type -->
  <div class="bar bar-mode">
    <span id="rushctl" class="ctl" style="display:none">
      <label class="ctl">Attackers
        <select id="attacker" class="sel">
          <option value="red">Red</option><option value="blue">Blue</option>
        </select></label>
      <label class="ctl">Defuse
        <select id="defuse" class="sel">
          <option value="0">Instant</option><option value="1">1s</option>
          <option value="2">2s</option><option value="3">3s</option>
          <option value="4">4s</option><option value="5">5s</option>
        </select></label>
    </span>
    <span id="domhint" class="modehint">King-of-the-Hill — hold the points; most cumulative time wins.</span>
  </div>
</header>
<div id="results">
  <div class="rtitle"></div>
  <table class="rtable">
    <thead><tr><th>Team</th><th>Total Held Time</th><th>Total Nodes Held</th></tr></thead>
    <tbody>
      <tr class="r-red"><td class="tm">RED</td><td class="tt"></td><td class="nn"></td></tr>
      <tr class="r-blue"><td class="tm">BLUE</td><td class="tt"></td><td class="nn"></td></tr>
    </tbody>
  </table>
  <div class="rwin"></div>
</div>
<div id="rushpanel">
  <div class="rushtop">
    <span class="phase"></span>
    <span class="sd">SUDDEN DEATH</span>
    <span class="rwin"></span>
  </div>
  <div class="bombs">
    <div class="bomb" data-b="0"><div class="bh"><span class="bn">Pink Hallway</span><span class="bf">1:00</span></div><div class="bs"></div><div class="bar"><div class="fill"></div></div><div class="arm"></div><div class="def"></div></div>
    <div class="bomb" data-b="1"><div class="bh"><span class="bn">Kill House</span><span class="bf">2:00</span></div><div class="bs"></div><div class="bar"><div class="fill"></div></div><div class="arm"></div><div class="def"></div></div>
    <div class="bomb" data-b="2"><div class="bh"><span class="bn">Dark Room</span><span class="bf">3:00</span></div><div class="bs"></div><div class="bar"><div class="fill"></div></div><div class="arm"></div><div class="def"></div></div>
  </div>
</div>
<div id="grid"><div class="empty">Waiting for nodes to report…</div></div>

<script>
const grid = document.getElementById('grid');
const statusEl = document.getElementById('status');
const clockEl = document.getElementById('clock');
const minutesEl = document.getElementById('minutes');
const startStop = document.getElementById('startStop');
const resultsEl = document.getElementById('results');
const nodes = {};   // key -> {data, arrival, lastMsg, stale}
let game = {running:false, remaining_s:0, duration_s:900};

// Friendly box names (node_id -> label), injected from the server. Falls back
// to the id for anything unlisted.
const LABELS = {{ labels|safe }};
function nodeName(id){ return LABELS[id] || (id||'?'); }

// --- Audio announcements (browser TTS + Web Audio tones) ---
let audioOn = false, audioCtx = null;
const SUMMARY_MS = 45000;   // state-summary cadence (ms)
function cap(s){ return s ? s[0].toUpperCase() + s.slice(1) : s; }
function joinNames(a){ a = a.map(cap);
  if (!a.length) return ''; if (a.length === 1) return a[0];
  if (a.length === 2) return a[0] + ' and ' + a[1];
  return a.slice(0,-1).join(', ') + ', and ' + a[a.length-1]; }
function tone(team){
  if (!audioOn) return;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)();
    const t = audioCtx.currentTime, o = audioCtx.createOscillator(), g = audioCtx.createGain();
    const base = team === 'red' ? 420 : team === 'blue' ? 620 : 520;
    o.type = 'sine'; o.frequency.setValueAtTime(base, t);
    o.frequency.exponentialRampToValueAtTime(base*1.5, t+0.12);
    g.gain.setValueAtTime(0.001, t);
    g.gain.exponentialRampToValueAtTime(0.3, t+0.02);
    g.gain.exponentialRampToValueAtTime(0.001, t+0.28);
    o.connect(g).connect(audioCtx.destination); o.start(t); o.stop(t+0.3);
  } catch(e){}
}
function say(text){
  if (!audioOn || !('speechSynthesis' in window) || !text) return;
  const u = new SpeechSynthesisUtterance(text); u.rate = 1.0; speechSynthesis.speak(u);
}
function gameStats(){
  let redT=0, blueT=0, redN=0, blueN=0;
  for (const k in nodes){ const d = nodes[k].data;
    redT += d.red_s||0; blueT += d.blue_s||0;
    if (d.owner==='red') redN++; else if (d.owner==='blue') blueN++; }
  return {redT, blueT, redN, blueN};
}
function winnerText(){ const s = gameStats();
  if (s.redT > s.blueT) return {team:'red', say:'Red wins'};
  if (s.blueT > s.redT) return {team:'blue', say:'Blue wins'};
  return {team:null, say:"it's a tie"}; }
function summarize(){
  const red=[], blue=[], neu=[];
  for (const k in nodes){ const n = nodes[k]; if (n.stale) continue;
    const id = nodeName(n.data.id);
    if (n.data.owner==='red') red.push(id);
    else if (n.data.owner==='blue') blue.push(id); else neu.push(id); }
  const total = red.length + blue.length + neu.length;
  if (!total) return '';
  if (red.length === total) return 'Red holds all ' + total + ' points.';
  if (blue.length === total) return 'Blue holds all ' + total + ' points.';
  const parts = [];
  if (red.length) parts.push('Red holds ' + joinNames(red));
  if (blue.length) parts.push('Blue holds ' + joinNames(blue));
  if (neu.length) parts.push(joinNames(neu) + (neu.length===1 ? ' is neutral' : ' are neutral'));
  return parts.join('. ') + '.';
}
// Voice packs: play a pre-rendered clip if the selected pack has it, else TTS.
let packs = {}, selectedPack = localStorage.getItem('voicePack') || '';
const clipQueue = []; let clipAudio = null;
function clipUrl(clip){
  if (selectedPack && packs[selectedPack] && packs[selectedPack].includes(clip + '.mp3'))
    return '/sounds/' + encodeURIComponent(selectedPack) + '/' + clip + '.mp3';
  return null;
}
function playNextClip(){
  const url = clipQueue.shift();
  if (!url){ clipAudio = null; return; }
  clipAudio = new Audio(url);
  clipAudio.onended = clipAudio.onerror = playNextClip;
  clipAudio.play().catch(() => playNextClip());
}
function playClip(url){ clipQueue.push(url); if (!clipAudio) playNextClip(); }
function announce(clip, ttsText, team){
  if (!audioOn) return;
  const url = clipUrl(clip);
  if (url) playClip(url); else { tone(team); say(ttsText); }
}
function loadPacks(){
  fetch('/api/packs').then(r => r.json()).then(d => {
    packs = d || {};
    const sel = document.getElementById('pack');
    sel.innerHTML = '<option value="">Browser voice</option>';
    Object.keys(packs).forEach(name => {
      const o = document.createElement('option'); o.value = name; o.textContent = name;
      sel.appendChild(o);
    });
    if (!(selectedPack && packs[selectedPack])) selectedPack = '';
    sel.value = selectedPack;
    sel.onchange = () => { selectedPack = sel.value; localStorage.setItem('voicePack', selectedPack); };
  }).catch(() => {});
}

function fmt(sec){
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec/60), s = sec % 60;
  return m + ':' + String(s).padStart(2,'0');
}
function liveSecs(n, team){
  const base = team === 'red' ? (n.data.red_s||0) : (n.data.blue_s||0);
  // Only tick when the GAME is running (fixes timers running while stopped).
  if (game.running && n.data.owner === team && !n.stale){
    return base + (Date.now() - n.arrival)/1000;
  }
  return base;
}
function sendCmd(body){
  return fetch('/api/command', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)
  }).catch(err => alert('Command failed: ' + err));
}
function renderGame(){
  clockEl.textContent = fmt(game.remaining_s);
  clockEl.className = !game.running && game.remaining_s === 0 ? 'over'
        : (!game.running ? 'idle' : (game.remaining_s <= 10 ? 'low' : ''));
  startStop.textContent = game.running ? 'Stop' : 'Start';
  startStop.classList.toggle('go', !game.running);
  startStop.classList.toggle('danger', game.running);
  renderResults();
  renderRush();
}
// End-of-game stats: aggregate held time + nodes held per team, and a winner.
function renderResults(){
  if (game.mode === 'rush'){ resultsEl.style.display = 'none'; return; }  // domination only
  const over = !game.running && game.remaining_s < game.duration_s;
  if (!over){ resultsEl.style.display = 'none'; return; }
  const {redT, blueT, redN, blueN} = gameStats();
  const q = s => resultsEl.querySelector(s);
  resultsEl.style.display = 'block';
  q('.rtitle').textContent = (game.remaining_s === 0) ? 'GAME OVER — TIME!' : 'GAME STOPPED';
  q('.r-red .tt').textContent = fmt(redT);   q('.r-red .nn').textContent = redN;
  q('.r-blue .tt').textContent = fmt(blueT); q('.r-blue .nn').textContent = blueN;
  q('.r-red .tt').classList.toggle('lead', redT > blueT);
  q('.r-blue .tt').classList.toggle('lead', blueT > redT);
  q('.r-red .nn').classList.toggle('lead', redN > blueN);
  q('.r-blue .nn').classList.toggle('lead', blueN > redN);
  const win = redT > blueT ? ['RED','ww-red'] : blueT > redT ? ['BLUE','ww-blue'] : null;
  q('.rwin').innerHTML = win
      ? ('WINNER (held time): <span class="'+win[1]+'">'+win[0]+'</span>')
      : 'TIE on total held time';
}
// Rush scoreboard: 3 bombs in sequence, the active one's arm progress, sudden
// death, and the winner. Driven entirely by the server's game.rush state.
const rushEl = document.getElementById('rushpanel');
function fmtms(sec){ sec = Math.max(0, Math.round(sec));
  return Math.floor(sec/60) + ':' + String(sec%60).padStart(2,'0'); }
function renderRush(){
  if (game.mode !== 'rush'){ rushEl.style.display = 'none'; return; }
  rushEl.style.display = 'block';
  const r = game.rush;
  const atk = game.attacker || 'red', def = atk === 'red' ? 'blue' : 'red';
  const phase = rushEl.querySelector('.phase');
  const sd = rushEl.querySelector('.sd');
  const win = rushEl.querySelector('.rwin');
  const bombs = rushEl.querySelectorAll('.bomb');
  const fuses = (r && r.fuses) || [60,120,180];
  bombs.forEach((b,i) => b.querySelector('.bf').textContent = fmtms(fuses[i]));
  if (!r){
    phase.textContent = 'RUSH — press Start (' + cap(atk) + ' attacking)';
    sd.style.display = 'none'; win.textContent = '';
    bombs.forEach(b => { b.className = 'bomb'; b.querySelector('.bs').textContent = 'PENDING';
      const f = b.querySelector('.fill'); f.className = 'fill'; f.style.width = '0';
      b.querySelector('.arm').textContent = ''; b.querySelector('.def').textContent = ''; });
    return;
  }
  sd.style.display = r.sudden_death ? 'inline-block' : 'none';
  phase.textContent = r.result ? '' :
      ('ATTACKERS: ' + cap(atk).toUpperCase() + '  •  BOMB ' + r.active + ' ACTIVE');
  if (r.result === 'attackers')
    win.innerHTML = '<span class="win-'+atk+'">'+cap(atk).toUpperCase()+' (ATTACKERS) WIN</span>';
  else if (r.result === 'defenders')
    win.innerHTML = '<span class="win-'+def+'">'+cap(def).toUpperCase()+' (DEFENDERS) WIN</span>';
  else win.textContent = '';
  bombs.forEach((b,i) => {
    const num = i + 1, done = r.detonated[i], active = (r.active === num) && !r.result;
    b.className = 'bomb' + (done ? ' done' : '') + (active ? ' active' : '');
    b.querySelector('.bs').textContent = done ? 'DETONATED'
        : (active ? (r.sudden_death && num === 3 ? 'SUDDEN DEATH' : 'ARMING') : 'PENDING');
    const fill = b.querySelector('.fill');
    fill.className = 'fill ' + ((active || done) ? atk : '');
    fill.style.width = (done ? 100 : (active ? Math.min(100, r.arm_s/fuses[i]*100) : 0)).toFixed(1) + '%';
    const arm = b.querySelector('.arm');
    const remaining = Math.max(0, fuses[i] - r.arm_s);
    arm.innerHTML = active
        ? '<span class="rem">' + fmtms(remaining) + '</span><span class="tot"> / ' + fmtms(fuses[i]) + '</span>'
        : '';
    const def = b.querySelector('.def');
    def.textContent = (active && r.sudden_death && num === 3 && game.defuse_s > 0)
        ? 'defuse ' + (r.defuse_hold_s||0).toFixed(1) + 's / ' + game.defuse_s + 's' : '';
  });
}
function ensureTile(key){
  let el = document.getElementById('tile-'+key);
  if (el) return el;
  const empty = grid.querySelector('.empty'); if (empty) empty.remove();
  el = document.createElement('div');
  el.className = 'tile'; el.id = 'tile-'+key;
  el.innerHTML = `
    <div class="thead">
      <span class="name"></span><span class="type"></span><span class="dot"></span>
    </div>
    <div class="row red"><span class="lbl">RED</span><span class="t rt">0:00</span></div>
    <div class="row blue"><span class="lbl">BLUE</span><span class="t bt">0:00</span></div>
    <div class="foot"><span class="cap"></span><button class="reset">Reset</button></div>`;
  grid.appendChild(el);
  return el;
}
function render(){
  const now = Date.now();
  for (const key in nodes){
    const n = nodes[key];
    n.stale = (n.data.status === 'offline') || (now - n.lastMsg > 30000);
    const el = ensureTile(key);
    el.dataset.type = n.data.type; el.dataset.id = n.data.id;
    el.classList.toggle('offline', n.stale);
    el.querySelector('.name').textContent = nodeName(n.data.id);
    el.querySelector('.type').textContent = n.data.type||'';
    el.querySelector('.dot').className = 'dot ' + (n.stale ? 'off' : 'on');
    const rRow = el.querySelector('.row.red'), bRow = el.querySelector('.row.blue');
    rRow.classList.toggle('own', n.data.owner === 'red' && !n.stale);
    bRow.classList.toggle('own', n.data.owner === 'blue' && !n.stale);
    el.querySelector('.rt').textContent = fmt(liveSecs(n,'red'));
    el.querySelector('.bt').textContent = fmt(liveSecs(n,'blue'));
    el.querySelector('.cap').textContent = (!n.stale && n.data.owner && n.data.owner!=='none')
        ? ('held by ' + n.data.owner) : (n.stale ? 'offline' : 'neutral');
  }
  renderResults();
}
// Controls.
grid.addEventListener('click', (e) => {
  if (!e.target.classList.contains('reset')) return;
  const tile = e.target.closest('.tile');
  const id = tile.dataset.id, type = tile.dataset.type;
  if (confirm('Reset ' + nodeName(id) + ' to neutral and zero its timers?'))
    sendCmd({scope:'node', type, id});
});
document.getElementById('resetAll').onclick = () => {
  if (confirm('Reset ALL control points to neutral and zero every timer?'))
    sendCmd({scope:'all'});
};
startStop.onclick = () => {
  if (game.running) {
    sendCmd({scope:'game', action:'stop'});
  } else if (confirm('Start a new ' + minutesEl.value + '-minute round? (zeros all timers)')) {
    sendCmd({scope:'game', action:'start', minutes: minutesEl.value});
  }
};
minutesEl.onchange = () => sendCmd({scope:'game', action:'settime', minutes: minutesEl.value});
// Mode + Rush controls.
const modeSel = document.getElementById('mode');
const rushCtl = document.getElementById('rushctl');
const domHint = document.getElementById('domhint');
const attackerSel = document.getElementById('attacker');
const defuseSel = document.getElementById('defuse');
modeSel.onchange = () => sendCmd({scope:'game', action:'setmode', mode: modeSel.value});
attackerSel.onchange = () => sendCmd({scope:'game', action:'setattacker', team: attackerSel.value});
defuseSel.onchange = () => sendCmd({scope:'game', action:'setdefuse', seconds: defuseSel.value});

const es = new EventSource('/events');
es.onopen = () => statusEl.textContent = 'live';
es.onerror = () => statusEl.textContent = 'reconnecting…';
es.onmessage = (e) => {
  const d = JSON.parse(e.data);
  if (d.kind === 'game') {
    const prev = game;
    // Sync the referee controls to the authoritative server state.
    if (d.mode) modeSel.value = d.mode;
    const isRush = (d.mode === 'rush');
    rushCtl.style.display = isRush ? 'inline-flex' : 'none';
    domHint.style.display = isRush ? 'none' : 'inline';
    if (d.attacker) attackerSel.value = d.attacker;
    if (typeof d.defuse_s === 'number') defuseSel.value = String(d.defuse_s);
    if (audioOn) {
      if (d.mode === 'rush' && d.rush) {
        const pr = prev.rush, nr = d.rush;
        const atk = d.attacker||'red', def = atk === 'red' ? 'blue' : 'red';
        if (pr) {
          for (let i=0;i<3;i++)
            if (nr.detonated[i] && !pr.detonated[i]) say('Bomb ' + (i+1) + ' detonated.');
          if (nr.sudden_death && !pr.sudden_death) say('Sudden death. Bomb three is live.');
          if (nr.result && !pr.result)
            say(nr.result === 'attackers' ? cap(atk)+' attackers win.' : cap(def)+' defenders win.');
        }
      } else {
        const mins = Math.round(d.duration_s/60);
        if (!prev.running && d.running) {
          announce('start', 'Game on. ' + mins + (mins===1?' minute.':' minutes.'), 'blue');
        } else if (prev.running && !d.running && d.remaining_s === 0) {
          const w = winnerText();
          announce('over_' + (w.team||'tie'), 'Time! ' + w.say + '.', w.team||'red');
        } else if (prev.running && d.running && prev.remaining_s > 60 && d.remaining_s <= 60) {
          announce('one_minute', 'One minute remaining.', null);
        }
      }
    }
    game = d; renderGame(); return;
  }
  const key = d.type + '/' + d.id;
  const prev = nodes[key];
  const prevOwner = prev ? prev.data.owner : null;
  const changed = !prev || prev.data.owner !== d.owner
      || prev.data.red_s !== d.red_s || prev.data.blue_s !== d.blue_s;
  nodes[key] = { data: d, lastMsg: Date.now(),
                 arrival: changed ? Date.now() : prev.arrival };
  render();
  if (audioOn && prev && prevOwner !== d.owner && (d.owner === 'red' || d.owner === 'blue')) {
    announce('cap_' + d.id + '_' + d.owner, nodeName(d.id) + ' taken by ' + cap(d.owner) + '.', d.owner);
  }
};
// Audio enable toggle — the tap also unlocks browser audio for this device.
const audioBtn = document.getElementById('audioBtn');
audioBtn.onclick = () => {
  audioOn = !audioOn;
  audioBtn.textContent = audioOn ? '🔊 Audio' : '🔇 Audio';
  audioBtn.classList.toggle('go', audioOn);
  if (audioOn) {
    try { if (!audioCtx) audioCtx = new (window.AudioContext||window.webkitAudioContext)();
          audioCtx.resume(); } catch(e){}
    announce('audio_enabled', 'Audio enabled.', null);
  } else if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
};
// Periodic spoken state summary while a round is running.
setInterval(() => {
  if (audioOn && game.running) {
    const s = summarize();
    if (s && !(speechSynthesis.speaking || speechSynthesis.pending)) say(s);
  }
}, SUMMARY_MS);
setInterval(render, 1000);
renderGame();
loadPacks();
</script>
</body>
</html>"""


if __name__ == "__main__":
    threading.Thread(target=_mqtt_loop, daemon=True).start()
    threading.Thread(target=_clock_loop, daemon=True).start()
    print(f"[dash] serving on http://0.0.0.0:{HTTP_PORT}")
    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True)
