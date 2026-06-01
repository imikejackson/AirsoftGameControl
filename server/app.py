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
import queue
import threading
import time

from flask import Flask, Response, request, jsonify, render_template_string
import paho.mqtt.client as mqtt

DASH_VERSION = 3            # bump on every dashboard change; shown in the header
MQTT_HOST = "localhost"
MQTT_PORT = 1883
TOPIC = "airsoft/#"
HTTP_PORT = 8080
DEFAULT_DURATION_S = 15 * 60

app = Flask(__name__)

_nodes = {}                 # "type/id" -> node dict
_nodes_lock = threading.Lock()
_subs = []                  # list[queue.Queue] for SSE clients
_subs_lock = threading.Lock()
_client = None              # the paho client, for publishing

# Authoritative game clock (this server owns it).
_game = {"running": False, "remaining_s": float(DEFAULT_DURATION_S),
         "duration_s": DEFAULT_DURATION_S}
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
        return {"kind": "game", "running": _game["running"],
                "remaining_s": int(round(_game["remaining_s"])),
                "duration_s": _game["duration_s"]}


def _publish_game():
    """Push the game clock to the broker (retained, authoritative) and the UI."""
    p = _game_payload()
    if _client is not None:
        _client.publish("airsoft/game/state",
                        json.dumps({"running": p["running"],
                                    "remaining_s": p["remaining_s"],
                                    "duration_s": p["duration_s"]}),
                        qos=1, retain=True)
    _broadcast(p)


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
            for f in ("owner", "red_s", "blue_s", "ip", "rssi"):
                if f in d:
                    n[f] = d[f]
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


def _clock_loop():
    """Tick the countdown and republish on each whole-second change."""
    last = time.time()
    last_pub = None
    while True:
        time.sleep(0.2)
        now = time.time()
        dt, last = now - last, now
        with _game_lock:
            if _game["running"] and _game["remaining_s"] > 0:
                _game["remaining_s"] = max(0.0, _game["remaining_s"] - dt)
                if _game["remaining_s"] <= 0:
                    _game["remaining_s"] = 0.0
                    _game["running"] = False  # game over
            cur = (int(round(_game["remaining_s"])), _game["running"])
        if cur != last_pub:
            last_pub = cur
            _publish_game()


@app.route("/")
def index():
    resp = Response(render_template_string(INDEX_HTML, ver=DASH_VERSION))
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
  header { padding:12px 18px; background:#15181d; border-bottom:1px solid #262b33;
           display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:18px; margin:0; font-weight:600; letter-spacing:.04em; }
  #status { font-size:13px; color:#7d8794; }
  .ver { font-size:11px; color:#7d8794; letter-spacing:.05em; }
  .spacer { margin-left:auto; }
  #clock { font-size:34px; font-weight:800; font-variant-numeric: tabular-nums;
           letter-spacing:.02em; }
  #clock.low { color:#ff5c5c; } #clock.over { color:#ff5c5c; }
  #clock.idle { color:#7d8794; }
  .ctl { display:flex; align-items:center; gap:8px; }
  input#minutes { width:56px; font:inherit; font-size:14px; text-align:center;
        background:#0d0f12; color:#e8e8e8; border:1px solid #3a414c; border-radius:6px; padding:5px; }
  button.btn { font:inherit; font-size:13px; font-weight:600; color:#e8e8e8;
        background:#2a2f37; border:1px solid #3a414c; border-radius:8px;
        padding:7px 12px; cursor:pointer; }
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
</style>
</head>
<body>
<header>
  <h1>AIRSOFT</h1>
  <span class="ver">dash v{{ ver }}</span>
  <span id="status">connecting…</span>
  <span class="spacer"></span>
  <span id="clock" class="idle">--:--</span>
  <span class="ctl"><input id="minutes" type="number" min="1" max="120" value="15"> min</span>
  <button class="btn go" id="startStop">Start</button>
  <button class="btn danger" id="resetAll">Reset All</button>
  <button class="btn" id="audioBtn">🔇 Audio</button>
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
    const id = n.data.id;
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
}
// End-of-game stats: aggregate held time + nodes held per team, and a winner.
function renderResults(){
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
    el.querySelector('.name').textContent = (n.data.id||'?').toUpperCase();
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
  if (confirm('Reset ' + id.toUpperCase() + ' to neutral and zero its timers?'))
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

const es = new EventSource('/events');
es.onopen = () => statusEl.textContent = 'live';
es.onerror = () => statusEl.textContent = 'reconnecting…';
es.onmessage = (e) => {
  const d = JSON.parse(e.data);
  if (d.kind === 'game') {
    if (audioOn) {
      const mins = Math.round(d.duration_s/60);
      if (!game.running && d.running) {
        tone('blue'); say('Game on. ' + mins + (mins===1?' minute.':' minutes.'));
      } else if (game.running && !d.running && d.remaining_s === 0) {
        const w = winnerText(); tone(w.team||'red'); say('Time! ' + w.say + '.');
      } else if (game.running && d.running && game.remaining_s > 60 && d.remaining_s <= 60) {
        say('One minute remaining.');
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
    tone(d.owner);
    say(cap(d.id) + ' taken by ' + cap(d.owner) + '.');
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
    say('Audio enabled.');
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
</script>
</body>
</html>"""


if __name__ == "__main__":
    threading.Thread(target=_mqtt_loop, daemon=True).start()
    threading.Thread(target=_clock_loop, daemon=True).start()
    print(f"[dash] serving on http://0.0.0.0:{HTTP_PORT}")
    app.run(host="0.0.0.0", port=HTTP_PORT, threaded=True)
