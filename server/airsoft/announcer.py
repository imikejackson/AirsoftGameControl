"""The announcer: decides WHEN the field speaker talks, in every game mode.

  round start     "Game on."
  time callouts   when the clock crosses 10:00, 5:00, 1:00, 0:30, 0:10 (each
                  switchable; ones longer than the round are skipped)
  time up         Timer mode: "Time! Game over."  Domination: the winner,
                  from the server's own scores.  Rush: nothing (it has its
                  own endings)
  reminders       each enabled reminder repeats every N minutes of GAME time
                  (pausing the clock pauses them), first plays staggered so
                  they don't stack, and a reminder due within REMINDER_GAP_S
                  of a callout waits instead of talking over it

The reminder catalog is every clip in voice_clips.csv whose name starts with
"reminder_". Referee choices persist in state/settings.json.
"""
import csv
import os
import threading

from . import audio, config, hub, settings

CALLOUTS = [            # (id = clip name, seconds remaining when it plays, label)
    ("start", None, "Game on (round start)"),
    ("ten_minutes", 600, "10 minutes"),
    ("five_minutes", 300, "5 minutes"),
    ("one_minute", 60, "1 minute"),
    ("thirty_seconds", 30, "30 seconds"),
    ("ten_seconds", 10, "10 seconds"),
    ("time_up", 0, "Time up"),
]
DEFAULT_REMINDERS = {   # clip -> (on, every_min) for a fresh server
    "reminder_dead_men": (True, 4),
    "reminder_call_hits": (True, 5),
    "reminder_eye_pro": (False, 6),
    "reminder_friendly_fire": (False, 7),
}
EVERY_CHOICES = [2, 3, 4, 5, 6, 7, 8, 10, 15]
REMINDER_GAP_S = 12     # keep reminders this far from any callout
REMINDER_RETRY_S = 15   # ...and try again this much later
STAGGER_S = 25          # offset between reminders' first plays
LAST_QUIET_S = 15       # no reminders in the final seconds of a round

_lock = threading.Lock()


def _catalog():
    path = os.path.join(config.SERVER_DIR, "voice_clips.csv")
    try:
        with open(path, newline="") as f:
            return [(r["clip"], r["text"]) for r in csv.DictReader(f)
                    if r["clip"].startswith("reminder_")]
    except FileNotFoundError:
        return [(c, c) for c in DEFAULT_REMINDERS]


def _load():
    saved = settings.load().get("announcer", {})
    callouts = {cid: saved.get("callouts", {}).get(cid, True) for cid, _, _ in CALLOUTS}
    reminders = {}
    for clip, text in _catalog():
        on, every = DEFAULT_REMINDERS.get(clip, (False, 5))
        s = saved.get("reminders", {}).get(clip, {})
        reminders[clip] = {"text": text, "on": bool(s.get("on", on)),
                           "every_min": int(s.get("every_min", every))}
    return callouts, reminders


_callouts, _reminders = _load()
_track = {"round": None, "remaining": None, "running": False, "next_due": {}}


def _save():
    settings.save("announcer", {
        "callouts": dict(_callouts),
        "reminders": {c: {"on": r["on"], "every_min": r["every_min"]}
                      for c, r in _reminders.items()}})


def config_payload():
    with _lock:
        return {"kind": "announcer",
                "callouts": [{"id": cid, "label": label, "on": _callouts[cid],
                              "have": audio.have(cid)} for cid, _, label in CALLOUTS],
                "reminders": [{"clip": c, "text": r["text"], "on": r["on"],
                               "every_min": r["every_min"], "have": audio.have(c)}
                              for c, r in _reminders.items()],
                "every_choices": EVERY_CHOICES}


def set_callout(cid, on):
    with _lock:
        if cid not in _callouts:
            return False
        _callouts[cid] = bool(on)
        _save()
    hub.broadcast(config_payload())
    return True


def set_reminder(clip, on=None, every_min=None):
    with _lock:
        r = _reminders.get(clip)
        if r is None:
            return False
        if on is not None:
            r["on"] = bool(on)
        if every_min is not None:
            if int(every_min) not in EVERY_CHOICES:
                return False
            r["every_min"] = int(every_min)
            _track["next_due"].pop(clip, None)   # reschedule from now on
        _save()
    hub.broadcast(config_payload())
    return True


def _domination_winner_clip(game):
    d = game.get("dom") or {}
    red, blue = int(d.get("red", 0)), int(d.get("blue", 0))
    return "over_red" if red > blue else "over_blue" if blue > red else "over_tie"


def tick():
    """Called by the clock loop every tick (no lock held)."""
    with hub.game_lock:
        g = hub.game
        running, remaining = g["running"], g["remaining_s"]
        duration, mode, rnd = g["duration_s"], g["mode"], g.get("round", 0)
        winner_clip = _domination_winner_clip(g) if mode == "domination" else None
    elapsed = duration - remaining
    say = []
    with _lock:
        t = _track
        prev = t["remaining"]
        if rnd != t["round"]:                       # a new round started
            t["round"], t["next_due"] = rnd, {}
            prev = None
            if running and _callouts["start"] and t["remaining"] is not None:
                say.append("start")
        # Time callouts: the clock crossed a mark (ignore marks >= the round
        # length so a 5-minute game doesn't announce "ten minutes").
        # (The clock stops the round in the same tick it reaches 0, so "time up"
        # is detected from the remaining time, not the running flag.)
        time_ran_out = prev is not None and prev > 0 and remaining == 0
        if prev is not None and (running or time_ran_out):
            for cid, mark, _ in CALLOUTS:
                if mark is None or not _callouts[cid]:
                    continue
                if mark == 0:
                    if time_ran_out:
                        if mode == "domination":
                            say.append(winner_clip)
                        elif mode == "timer":
                            say.append("time_up")
                elif mark < duration and prev > mark >= remaining:
                    say.append(cid)
        # Reminders, in game time.
        if running and remaining > LAST_QUIET_S:
            marks = [m for cid, m, _ in CALLOUTS if m and _callouts[cid] and m < duration]
            on = [c for c, r in _reminders.items() if r["on"]]
            for i, clip in enumerate(on):
                every = _reminders[clip]["every_min"] * 60
                due = t["next_due"].setdefault(clip, min(every, 60) + i * STAGGER_S
                                               if elapsed < 1 else elapsed + every)
                if elapsed < due:
                    continue
                if any(abs(remaining - m) < REMINDER_GAP_S for m in marks) or say:
                    t["next_due"][clip] = elapsed + REMINDER_RETRY_S
                    continue
                say.append(clip)
                t["next_due"][clip] = elapsed + every
                break                               # at most one reminder per tick
        t["remaining"], t["running"] = remaining, running
    for clip in say:
        audio.play(clip)
