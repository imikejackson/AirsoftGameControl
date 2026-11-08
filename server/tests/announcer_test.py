#!/usr/bin/env python3
"""Announcer + Timer mode test: runs a real 2-minute Timer game (with a 5 s
pause) against a RUNNING bench dashboard and checks which clips play when.
Takes about 2.5 minutes and plays through the bench machine's speakers.

    python server/tests/announcer_test.py [--url http://127.0.0.1:8080] [--pin-file server/ref_pin.txt]

Never run it against the field server during a game.
"""
import argparse
import http.cookiejar
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8080")
ap.add_argument("--pin-file", default="server/ref_pin.txt")
args = ap.parse_args()
B = args.url.rstrip("/")
PIN = open(args.pin_file).read().strip()
failures = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


ref = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
anon = urllib.request.build_opener()


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


def cmd(body):
    return req(ref, "/api/command", data=body)[0]


played = []      # (game elapsed s, clip)
game = {}


def sse():
    r = urllib.request.urlopen(B + "/events", timeout=600)
    buf, last_playing = b"", None
    while True:
        buf += r.read1(65536)
        *lines, buf = buf.split(b"\n")
        for line in lines:
            if not line.startswith(b"data: "):
                continue
            d = json.loads(line[6:])
            if d.get("kind") == "game":
                game.update(d)
            elif d.get("kind") == "audio" and d.get("playing") and d["playing"] != last_playing:
                el = game.get("duration_s", 0) - game.get("remaining_s", 0)
                played.append((el, d["playing"]))
            if d.get("kind") == "audio":
                last_playing = d.get("playing")


threading.Thread(target=sse, daemon=True).start()
time.sleep(1)

print("timer page and settings")
check("/ref/timer needs login", req(anon, "/ref/timer")[1].find("Enter the 6-digit PIN") >= 0)
check("/api/announcer needs login", req(anon, "/api/announcer")[0] == 403)
req(ref, "/ref", form={"pin": PIN})
st, h = req(ref, "/ref/timer")
check("/ref/timer loads for a referee", st == 200 and "TIMER &amp; AUDIO" in h)
a = json.loads(req(ref, "/api/announcer")[1])
check("announcer lists 7 callouts", len(a["callouts"]) == 7, [c["id"] for c in a["callouts"]])
check("announcer lists the reminders", len(a["reminders"]) >= 4, [r["clip"] for r in a["reminders"]])
check("all clips present on disk", all(c["have"] for c in a["callouts"] + a["reminders"]))
check("unknown clip rejected", cmd({"scope": "audio", "action": "play", "clip": "../../etc"}) == 400)
check("bad repeat interval rejected",
      cmd({"scope": "audio", "action": "reminder", "clip": "reminder_dead_men", "every_min": 9}) == 400)
# Known settings for the run: all callouts on; dead men every 4, call hits every 5, others off.
for c in a["callouts"]:
    cmd({"scope": "audio", "action": "callout", "id": c["id"], "on": True})
for r in a["reminders"]:
    on = r["clip"] in ("reminder_dead_men", "reminder_call_hits")
    every = {"reminder_dead_men": 4, "reminder_call_hits": 5}.get(r["clip"], r["every_min"])
    cmd({"scope": "audio", "action": "reminder", "clip": r["clip"], "on": on, "every_min": every})
check("speaker on", cmd({"scope": "audio", "action": "speaker", "on": True}) == 200)

print("2-minute timer game with a pause (about 2.5 minutes)")
check("switch to Timer mode", cmd({"scope": "game", "action": "setmode", "mode": "timer"}) == 200)
check("start", cmd({"scope": "game", "action": "start", "minutes": 2}) == 200)
time.sleep(20)
check("pause", cmd({"scope": "game", "action": "stop"}) == 200)
time.sleep(1)
paused_at = game.get("remaining_s")
time.sleep(5)
check("clock frozen while paused", game.get("remaining_s") == paused_at, (paused_at, game.get("remaining_s")))
check("resume", cmd({"scope": "game", "action": "resume"}) == 200)
t0 = time.time()
while time.time() - t0 < 110 and (game.get("running") or game.get("remaining_s", 1) > 0):
    time.sleep(1)
time.sleep(3)
print("  played:", ", ".join(f"{c}@{el:.0f}s" for el, c in played))
clips = [c for _, c in played]
expect = ["start", "one_minute", "reminder_dead_men", "thirty_seconds", "ten_seconds", "time_up"]
check("clips in the expected order", clips == expect, clips)
times = dict((c, el) for el, c in played)
for clip, at in (("one_minute", 60), ("thirty_seconds", 90), ("ten_seconds", 110), ("time_up", 120)):
    check(f"{clip} at {at} s game time", clip in times and abs(times[clip] - at) <= 2, times.get(clip))
check("reminder waited for the callout (60 s -> ~75 s)",
      "reminder_dead_men" in times and 73 <= times["reminder_dead_men"] <= 77, times.get("reminder_dead_men"))
check("round ended", not game.get("running") and game.get("remaining_s") == 0)
cmd({"scope": "game", "action": "setmode", "mode": "domination"})

print()
print("ALL PASSED" if not failures else f"{len(failures)} FAILED: " + ", ".join(failures))
sys.exit(1 if failures else 0)
