"""Rush: the attackers arm three bombs in sequence across the control points.

Arm progress on the active bomb = the attacking team's hold time on that box,
accrued HERE from box ownership: while the attacker owns the active bomb's box
the timer advances; a defender holding it pauses it (attackers resume where
they left off). When a bomb detonates the next one becomes active. If time
runs out while bomb 3 is still armable, it's sudden death: the attackers can
still arm it, and the defenders win by holding it for the referee-set defuse
time. Each box gets a retained role (off/pending/active/detonated) so it can
lock and show the right screen.
"""
from flask import jsonify

from .. import hub
from . import Mode

RUSH_ORDER = [("controlpoint", "alpha"),    # bomb #1 = Pink Hallway
              ("controlpoint", "bravo"),    # bomb #2 = Kill House
              ("controlpoint", "charlie")]  # bomb #3 = Dark Room
RUSH_FUSES = [60, 120, 180]   # bomb #1/#2/#3 fuse seconds (1/2/3 min)
RUSH_DEFUSE_MAX = 5           # cap on the sudden-death defuse hold (s)


def bomb_owner(active):
    """Current owner ('red'/'blue'/'none') of the active bomb's box, or None."""
    if active < 1 or active > 3:
        return None
    ntype, nid = RUSH_ORDER[active - 1]
    with hub.nodes_lock:
        n = hub.nodes.get(f"{ntype}/{nid}")
        return (n.get("owner") if n else None)


class Rush(Mode):
    name = "rush"
    label = "Rush"

    def __init__(self):
        self._last_status_pub = None   # dedup for the retained per-box roles

    def init(self, game):
        game["attacker"] = "red"       # the arming team (referee-set)
        game["defuse_s"] = 0           # 0..RUSH_DEFUSE_MAX sudden-death hold
        # Runtime state while a Rush round is set up, else None:
        # {active, detonated[3], arm_s, fuses[3], sudden_death,
        #  defuse_hold_s, _defuse_start, result}
        game["rush"] = None

    def on_select(self, game):
        game["rush"] = None

    def on_start(self, game, active):
        game["rush"] = ({"active": 1, "detonated": [False, False, False],
                         "arm_s": 0.0, "fuses": list(RUSH_FUSES),
                         "sudden_death": False, "defuse_hold_s": 0.0,
                         "_defuse_start": None, "result": None}
                        if active else None)

    def on_time_up(self, game):
        r = game.get("rush")
        if r is None or r["result"] is not None:
            return False
        if r["active"] >= 3 and not r["detonated"][2]:
            r["sudden_death"] = True      # bomb-3 race; keep running
            return True
        r["result"] = "defenders"         # held them off to time
        return False

    def tick(self, now, dt):
        with hub.game_lock:
            g = hub.game
            r = g.get("rush")
            if r is None or r["result"] is not None:
                return
            attacker = g["attacker"]
            defender = "blue" if attacker == "red" else "red"
            running = g["running"]
            defuse_target = float(g["defuse_s"])
            active, sudden = r["active"], r["sudden_death"]
        if not 1 <= active <= 3:
            return
        owner = bomb_owner(active)
        with hub.game_lock:
            r = hub.game["rush"]
            if r is None or r["result"] is not None or r["active"] != active:
                return
            if (running or sudden) and owner == attacker:
                r["arm_s"] += dt                       # attackers arming
            if r["arm_s"] >= r["fuses"][active - 1]:    # boom
                r["detonated"][active - 1] = True
                if active >= 3:
                    r["result"] = "attackers"
                    hub.game["running"] = False
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
                        hub.game["running"] = False
                else:
                    r["_defuse_start"] = None
                    r["defuse_hold_s"] = 0.0

    def after_tick(self):
        """Publish each box's retained Rush role (off/pending/active/detonated)
        so it locks + shows the right thing. Only publishes on a change."""
        with hub.game_lock:
            r = hub.game.get("rush")
            on = (hub.game["mode"] == "rush" and r is not None
                  and hub.game["running"] and r["result"] is None)
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
        if sig == self._last_status_pub:
            return
        self._last_status_pub = sig
        if hub.client is not None:
            for (ntype, nid), st in zip(RUSH_ORDER, statuses):
                hub.publish(f"airsoft/{ntype}/{nid}/rush", st, retain=True)
            print(f"[dash] rush status -> {statuses}")

    def payload(self, game):
        p = {"attacker": game["attacker"], "defuse_s": game["defuse_s"]}
        r = game.get("rush")
        if r is not None:
            p["rush"] = {"active": r["active"], "detonated": list(r["detonated"]),
                         "arm_s": int(round(r["arm_s"])), "fuses": list(r["fuses"]),
                         "sudden_death": r["sudden_death"],
                         "defuse_hold_s": round(r["defuse_hold_s"], 1),
                         "result": r["result"]}
        return p

    def node_fields(self, p):
        r = p.get("rush")
        if r is None:
            return {}
        a = r["active"]
        return {"attacker": p["attacker"],              # which team is arming
                "arm_s": r["arm_s"],                    # active bomb's arm progress (s)
                "fuse_s": r["fuses"][a - 1] if 1 <= a <= 3 else 0}

    def signature(self, game):
        r = game.get("rush")
        return ((r["active"] if r else None),
                (int(round(r["arm_s"])) if r else None),
                (r["sudden_death"] if r else None),
                (r["result"] if r else None),
                (int(r["defuse_hold_s"]) if r else None),
                (tuple(r["detonated"]) if r else None))

    def command(self, action, body):
        if action == "setattacker":      # which team attacks
            t = body.get("team", "red")
            if t not in ("red", "blue"):
                return jsonify(ok=False, error="bad team"), 400
            with hub.game_lock:
                hub.game["attacker"] = t
            hub.publish_game()
            return jsonify(ok=True)
        if action == "setdefuse":        # sudden-death defuse hold (0..MAX)
            try:
                s = int(body.get("seconds", 0))
            except (TypeError, ValueError):
                s = 0
            with hub.game_lock:
                hub.game["defuse_s"] = max(0, min(RUSH_DEFUSE_MAX, s))
            hub.publish_game()
            return jsonify(ok=True)
        return None
