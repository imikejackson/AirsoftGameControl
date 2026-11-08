"""Domination: score-based King of the Hill across all control points.

Scored HERE from box ownership (the boxes stay mode-agnostic sensors). Every
box a team holds earns it 1 point every DOM_TICK_S seconds. "Rubber band"
catch-up: as one team's lead grows, the leader's points come slower and the
trailer's come faster, so a team that falls behind can still claw back.
DOM_CATCHUP[level] is the full-strength ratio of the trailer's per-box rate to
the leader's. Nothing happens until the lead passes DOM_DEADZONE_PTS (so a
modest lead earned by playing well is never eroded by even play); beyond that
it ramps in linearly over the next DOM_RAMP_PTS, and is split evenly (leader /
sqrt, trailer * sqrt). Holding more boxes always still matters: at "medium"
(2x) the trailer must hold half as many boxes as the leader just to keep pace.
"""
import time

from flask import jsonify

from .. import hub
from . import Mode

DOM_TICK_S = 5.0              # base: 1 point per held box every 5 s
DOM_DEADZONE_PTS = 20         # leads up to this are left alone
DOM_RAMP_PTS = 30             # catch-up reaches full strength this far past the dead zone
DOM_CATCHUP = {"off": 1.0, "low": 1.5, "medium": 2.0, "high": 3.0}
DOM_DEFAULT_CATCHUP = "medium"
DOM_STALE_S = 30              # a box silent this long stops scoring (matches the UI)


def zero():
    return {"red": 0.0, "blue": 0.0, "red_rate": 0.0, "blue_rate": 0.0,
            "red_mult": 1.0, "blue_mult": 1.0}


def held_counts():
    """(red, blue) number of live control points each team currently holds.
    Offline or long-silent boxes don't score."""
    now = time.time()
    red = blue = 0
    with hub.nodes_lock:
        for n in hub.nodes.values():
            if n.get("type") != "controlpoint" or n.get("status") == "offline":
                continue
            if now - n.get("last_seen", 0) > DOM_STALE_S:
                continue
            if n.get("owner") == "red":
                red += 1
            elif n.get("owner") == "blue":
                blue += 1
    return red, blue


def multipliers(red_score, blue_score, catchup):
    """Rubber band: (red_mult, blue_mult) applied to each team's per-box rate.
    Leads up to DOM_DEADZONE_PTS are left alone; past that the leader's rate
    drops and the trailer's rises, reaching a trailer/leader ratio of
    DOM_CATCHUP[catchup] at a lead of DOM_DEADZONE_PTS + DOM_RAMP_PTS."""
    swing = DOM_CATCHUP.get(catchup, 1.0)
    excess = max(0, abs(red_score - blue_score) - DOM_DEADZONE_PTS)
    ratio = 1.0 + (swing - 1.0) * min(1.0, excess / DOM_RAMP_PTS)
    half = ratio ** 0.5                     # split evenly between the two teams
    if red_score > blue_score:
        return 1.0 / half, half
    if blue_score > red_score:
        return half, 1.0 / half
    return 1.0, 1.0


class Domination(Mode):
    name = "domination"
    label = "Domination"

    def init(self, game):
        game["catchup"] = DOM_DEFAULT_CATCHUP
        game["dom"] = zero()

    def on_select(self, game):
        game["dom"] = zero()

    def on_start(self, game, active):
        game["dom"] = zero()        # scores always start from 0 on a new round

    def on_reset_all(self, game):
        game["dom"] = zero()        # "zero every timer" includes the scores

    def tick(self, now, dt):
        # The lead is measured on the displayed (whole-point) scores so the
        # rates players see match the numbers on the board.
        red_boxes, blue_boxes = held_counts()
        with hub.game_lock:
            g = hub.game
            running = g["running"]
            d = g["dom"]
            rm, bm = multipliers(int(d["red"]), int(d["blue"]), g["catchup"])
            d["red_mult"], d["blue_mult"] = rm, bm
            d["red_rate"] = red_boxes * rm / DOM_TICK_S if running else 0.0
            d["blue_rate"] = blue_boxes * bm / DOM_TICK_S if running else 0.0
            d["red"] += d["red_rate"] * dt
            d["blue"] += d["blue_rate"] * dt

    def payload(self, game):
        d = game["dom"]
        return {"catchup": game["catchup"],
                "dom": {"red": int(d["red"]), "blue": int(d["blue"]),
                        "red_ppm": round(d["red_rate"] * 60, 1),
                        "blue_ppm": round(d["blue_rate"] * 60, 1),
                        "red_mult": round(d["red_mult"], 2),
                        "blue_mult": round(d["blue_mult"], 2)}}

    def node_fields(self, p):
        # Team scores, for any box display that wants them (ignored otherwise).
        return {"score_red": p["dom"]["red"], "score_blue": p["dom"]["blue"]}

    def signature(self, game):
        d = game["dom"]
        return (game["catchup"], int(d["red"]), int(d["blue"]),
                round(d["red_rate"] * 60, 1), round(d["blue_rate"] * 60, 1))

    def command(self, action, body):
        if action == "setcatchup":       # rubber-band strength, allowed mid-round
            level = body.get("level", DOM_DEFAULT_CATCHUP)
            if level not in DOM_CATCHUP:
                return jsonify(ok=False, error="bad level"), 400
            with hub.game_lock:
                hub.game["catchup"] = level
            hub.publish_game()
            return jsonify(ok=True)
        return None
