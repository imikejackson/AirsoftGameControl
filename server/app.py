#!/usr/bin/env python3
"""Airsoft Control Point — live web dashboard + game controls.

Subscribes to the MQTT broker, keeps live box state in memory, and serves a
self-updating scoreboard over Server-Sent Events. It is also the GAME-CLOCK
AUTHORITY: it owns the countdown, publishes the retained airsoft/game/state,
and ends the round at zero. The code lives in the airsoft/ package (see
airsoft/__init__.py for the layout); this file just starts it.

Open http://<server>:8080  (e.g. http://airsoft-pi.local:8080).
  /      read-only PLAYER view — anyone
  /ref   REFEREE page with the game controls — needs the 6-digit PIN

Deploy: copy app.py, airsoft/, templates/, voice_clips.csv and sounds/field/
together (see AGENTS.md section 10), not just this file.
"""
import threading

from airsoft import audio, bridge, clock, config
from airsoft.web import app

if __name__ == "__main__":
    threading.Thread(target=bridge.run, daemon=True).start()
    threading.Thread(target=clock.run, daemon=True).start()
    audio.start()
    print(f"[dash] serving on http://0.0.0.0:{config.HTTP_PORT}")
    app.run(host="0.0.0.0", port=config.HTTP_PORT, threaded=True)
