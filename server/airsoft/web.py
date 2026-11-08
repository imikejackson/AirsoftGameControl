"""Flask routes: the player and referee pages, the live event stream, sounds,
and the referee command API.

  /      read-only PLAYER view (scores, clock, box ownership) — anyone
  /ref   REFEREE page with the game controls — needs the 6-digit PIN
Every command (/api/command) requires a referee login; hiding buttons is not
what protects the game, this check is.
"""
import json
import os
import queue
from datetime import timedelta

from flask import (Flask, Response, abort, jsonify, redirect, render_template,
                   request, send_from_directory, session)

from . import auth, config, connmon, hub, modes

app = Flask(__name__, template_folder=config.TEMPLATES_DIR)
app.secret_key = os.urandom(32)
app.permanent_session_lifetime = timedelta(hours=12)


def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store"  # always serve the latest page
    return resp


def _page(ref):
    return _no_store(Response(render_template(
        "dashboard.html", ver=config.DASH_VERSION, ref=ref,
        labels=json.dumps(config.NODE_LABELS))))


@app.route("/")
def index():
    """Player view: live scores/clock/ownership, no controls."""
    return _page(ref=False)


@app.route("/ref", methods=["GET", "POST"])
def ref():
    """Referee page; asks for the PIN until this browser has logged in."""
    error = None
    if request.method == "POST":
        error = auth.try_login(request.remote_addr or "?", request.form.get("pin", ""))
        if error is None:
            return redirect("/ref")
    if auth.is_ref():
        return _page(ref=True)
    return _no_store(Response(render_template("login.html", ver=config.DASH_VERSION,
                                              error=error)))


@app.route("/ref/logout")
def ref_logout():
    session.clear()
    return redirect("/")


@app.route("/api/connlog")
def connlog():
    """Recent connection events (newest last), referee only."""
    if not auth.is_ref():
        return jsonify(ok=False, error="referee login required"), 403
    with hub.nodes_lock:
        return jsonify(list(connmon.recent))


@app.route("/events")
def events():
    def stream():
        q = hub.subscribe()
        try:
            yield f"data: {json.dumps(hub.game_payload())}\n\n"
            with hub.nodes_lock:
                snap = [dict(n) for n in hub.nodes.values()]
            for n in snap:
                yield f"data: {json.dumps(n)}\n\n"
            while True:
                try:
                    yield f"data: {q.get(timeout=15)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            hub.unsubscribe(q)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/packs")
def packs():
    """List voice packs (subdirs of sounds/) and the .mp3 clips in each."""
    out = {}
    try:
        for name in sorted(os.listdir(config.SOUNDS_DIR)):
            d = os.path.join(config.SOUNDS_DIR, name)
            if os.path.isdir(d):
                out[name] = sorted(f for f in os.listdir(d) if f.lower().endswith(".mp3"))
    except FileNotFoundError:
        pass
    return jsonify(out)


@app.route("/sounds/<pack>/<path:fname>")
def sound(pack, fname):
    if "/" in pack or pack.startswith("."):
        abort(404)
    return send_from_directory(os.path.join(config.SOUNDS_DIR, pack), fname)


def _game_command(action, body):
    if action == "start":                # fresh round: reset scores + full clock
        with hub.game_lock:
            g = hub.game
            mins = float(body.get("minutes", g["duration_s"] / 60))
            g["duration_s"] = max(1, int(mins * 60))
            g["remaining_s"] = float(g["duration_s"])
            g["running"] = True
            for m in modes.ALL:
                m.on_start(g, active=(m.name == g["mode"]))
        hub.publish("airsoft/game/command", "reset_all")
        connmon.new_round()
        hub.publish_game()
    elif action == "stop":               # freeze everything
        with hub.game_lock:
            hub.game["running"] = False
        hub.publish_game()
    elif action == "settime":            # set duration (and idle countdown)
        with hub.game_lock:
            mins = float(body.get("minutes", 15))
            hub.game["duration_s"] = max(1, int(mins * 60))
            if not hub.game["running"]:
                hub.game["remaining_s"] = float(hub.game["duration_s"])
        hub.publish_game()
    elif action == "setmode":            # only when idle
        m = body.get("mode", "domination")
        if m not in modes.BY_NAME:
            return jsonify(ok=False, error="bad mode"), 400
        with hub.game_lock:
            if not hub.game["running"]:
                hub.game["mode"] = m
                for mode in modes.ALL:
                    mode.on_select(hub.game)
        hub.publish_game()
    else:
        for m in modes.ALL:              # mode-specific settings
            resp = m.command(action, body)
            if resp is not None:
                return resp
        return jsonify(ok=False, error="bad action"), 400
    return jsonify(ok=True)


@app.route("/api/command", methods=["POST"])
def command():
    if not auth.is_ref():
        return jsonify(ok=False, error="referee login required"), 403
    if hub.client is None:
        return jsonify(ok=False, error="broker not connected"), 503
    body = request.get_json(force=True, silent=True) or {}
    scope = body.get("scope")
    action = body.get("action", "reset")

    if scope == "game":
        return _game_command(action, body)
    if scope == "all":
        topic, payload = "airsoft/game/command", "reset_all"
        with hub.game_lock:
            for m in modes.ALL:
                m.on_reset_all(hub.game)
        hub.publish_game()
    elif scope == "node":
        ntype, nid = body.get("type"), body.get("id")
        if not ntype or not nid:
            return jsonify(ok=False, error="missing type/id"), 400
        topic, payload = f"airsoft/{ntype}/{nid}/command", "reset"
    else:
        return jsonify(ok=False, error="bad scope"), 400

    hub.publish(topic, payload)
    print(f"[dash] command -> {topic} = {payload}")
    return jsonify(ok=True, topic=topic, payload=payload)
