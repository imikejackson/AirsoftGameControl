#!/usr/bin/env python3
"""Airsoft Control Point — live web dashboard.

Subscribes to the MQTT broker, keeps live node state in memory, and serves a
self-updating scoreboard over Server-Sent Events. Single file: Flask +
paho-mqtt with all HTML/JS embedded. Nodes are auto-discovered — a tile appears
as soon as a node publishes.

The firmware publishes game state on ownership change (plus heartbeats for
liveness), so the browser extrapolates the owning team's ticking time between
captures. Open http://<pi>:8080  (e.g. http://airsoft-pi.local:8080).
"""
import json
import queue
import threading
import time

from flask import Flask, Response, render_template_string
import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
TOPIC = "airsoft/#"
HTTP_PORT = 8080

app = Flask(__name__)

_nodes = {}                 # "type/id" -> node dict
_nodes_lock = threading.Lock()
_subs = []                  # list[queue.Queue] for SSE clients
_subs_lock = threading.Lock()


def _broadcast(node):
    data = json.dumps(node)
    with _subs_lock:
        for q in list(_subs):
            try:
                q.put_nowait(data)
            except queue.Full:
                pass


def _touch(ntype, nid):
    key = f"{ntype}/{nid}"
    n = _nodes.get(key)
    if n is None:
        n = {"type": ntype, "id": nid, "owner": "none", "red_s": 0,
             "blue_s": 0, "status": "online", "rssi": None, "ip": None}
        _nodes[key] = n
    n["last_seen"] = time.time()
    return n


def _on_connect(client, userdata, flags, rc, *args):
    print(f"[dash] connected to broker (rc={rc}); subscribing to {TOPIC}")
    client.subscribe(TOPIC)


def _on_message(client, userdata, msg):
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
            for f in ("owner", "red_s", "blue_s", "ip", "rssi"):
                if f in d:
                    n[f] = d[f]
            # A state message carrying game fields re-baselines the timers.
            if kind == "state" and ("owner" in d or "red_s" in d):
                n["updated"] = time.time()
            if kind == "heartbeat":
                n["status"] = "online"
        snapshot = dict(n)
    _broadcast(snapshot)


def _mqtt_loop():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)  # paho 2.x
    except (AttributeError, TypeError):
        client = mqtt.Client()                                  # paho 1.x
    client.on_connect = _on_connect
    client.on_message = _on_message
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, 60)
            client.loop_forever()
        except Exception as e:  # noqa: BLE001 — keep the bridge alive
            print(f"[dash] mqtt error: {e}; retrying in 3s")
            time.sleep(3)


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/events")
def events():
    def stream():
        q = queue.Queue(maxsize=200)
        with _subs_lock:
            _subs.append(q)
        try:
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
  header { padding:14px 18px; background:#15181d; border-bottom:1px solid #262b33;
           display:flex; align-items:center; gap:12px; }
  header h1 { font-size:18px; margin:0; font-weight:600; letter-spacing:.04em; }
  header .sub { color:#7d8794; font-size:13px; }
  #status { margin-left:auto; font-size:13px; color:#7d8794; }
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
          justify-content:space-between; border-top:1px solid #262b33; min-height:30px; }
  .cap { color:#ffcf5c; font-weight:600; }
  .empty { color:#7d8794; padding:40px; text-align:center; }
</style>
</head>
<body>
<header>
  <h1>AIRSOFT CONTROL POINTS</h1>
  <span class="sub">live scoreboard</span>
  <span id="status">connecting…</span>
</header>
<div id="grid"><div class="empty">Waiting for nodes to report…</div></div>

<script>
const grid = document.getElementById('grid');
const statusEl = document.getElementById('status');
const nodes = {};   // key -> {data, arrival}

function fmt(sec){
  sec = Math.max(0, Math.floor(sec));
  const m = Math.floor(sec/60), s = sec % 60;
  return m + ':' + String(s).padStart(2,'0');
}
function liveSecs(n, team){
  const base = team === 'red' ? (n.data.red_s||0) : (n.data.blue_s||0);
  // The owning team's timer ticks since we last got a state update.
  if (n.data.owner === team && !n.stale){
    return base + (Date.now() - n.arrival)/1000;
  }
  return base;
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
    <div class="foot"><span class="ip"></span><span class="cap"></span></div>`;
  grid.appendChild(el);
  return el;
}
function render(){
  const now = Date.now();
  for (const key in nodes){
    const n = nodes[key];
    n.stale = (n.data.status === 'offline') || (now - n.arrival > 30000);
    const el = ensureTile(key);
    el.classList.toggle('offline', n.stale);
    el.querySelector('.name').textContent = (n.data.id||'?').toUpperCase();
    el.querySelector('.type').textContent = n.data.type||'';
    const dot = el.querySelector('.dot');
    dot.className = 'dot ' + (n.stale ? 'off' : 'on');
    const rRow = el.querySelector('.row.red'), bRow = el.querySelector('.row.blue');
    rRow.classList.toggle('own', n.data.owner === 'red' && !n.stale);
    bRow.classList.toggle('own', n.data.owner === 'blue' && !n.stale);
    el.querySelector('.rt').textContent = fmt(liveSecs(n,'red'));
    el.querySelector('.bt').textContent = fmt(liveSecs(n,'blue'));
    el.querySelector('.ip').textContent = n.data.ip || '';
    const cap = el.querySelector('.cap');
    cap.textContent = (!n.stale && n.data.owner && n.data.owner!=='none')
        ? ('held by ' + n.data.owner) : (n.stale ? 'offline' : 'neutral');
  }
}
const es = new EventSource('/events');
es.onopen = () => statusEl.textContent = 'live';
es.onerror = () => statusEl.textContent = 'reconnecting…';
es.onmessage = (e) => {
  const d = JSON.parse(e.data);
  const key = d.type + '/' + d.id;
  const prev = nodes[key];
  // Re-baseline the tick clock only when the timers/owner actually changed.
  const changed = !prev || prev.data.owner !== d.owner
      || prev.data.red_s !== d.red_s || prev.data.blue_s !== d.blue_s;
  nodes[key] = { data: d, arrival: changed ? Date.now() : prev.arrival };
  render();
};
setInterval(render, 1000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    threading.Thread(target=_mqtt_loop, daemon=True).start()
    print(f"[dash] serving on http://0.0.0.0:{HTTP_PORT}")
    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True)
