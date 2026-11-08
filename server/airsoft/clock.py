"""The game clock loop: ticks the countdown and the selected mode 5x/s, runs
the connection watchdog, and republishes the game state when it changes."""
import time

from . import announcer, connmon, hub, modes


def run():
    last = time.time()
    last_pub = None
    while True:
        time.sleep(0.2)
        now = time.time()
        dt, last = now - last, now

        # 1) Countdown. At 0 the mode decides whether play continues (Rush
        # sudden death) or the round ends.
        with hub.game_lock:
            g = hub.game
            mode = modes.current(g["mode"])
            if g["running"] and g["remaining_s"] > 0:
                g["remaining_s"] = max(0.0, g["remaining_s"] - dt)
                if g["remaining_s"] <= 0:
                    g["remaining_s"] = 0.0
                    if not mode.on_time_up(g):
                        g["running"] = False

        # 2) The selected mode's own logic (scoring, arming, ...).
        mode.tick(now, dt)

        # 3) Connection watchdog, and the field-speaker announcer.
        connmon.watchdog(now)
        announcer.tick()

        # 4) Publish on any meaningful change.
        with hub.game_lock:
            g = hub.game
            cur = (int(round(g["remaining_s"])), g["running"], g["mode"],
                   tuple(m.signature(g) for m in modes.ALL))
        if cur != last_pub:
            last_pub = cur
            hub.publish_game()
        for m in modes.ALL:
            m.after_tick()          # e.g. Rush's retained per-box roles (deduped)
