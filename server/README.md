# Airsoft Dashboard (Raspberry Pi)

Live web scoreboard for the control-point network. Subscribes to the Mosquitto
broker and serves an auto-updating page (one tile per node) at
`http://airsoft-pi.local:8080`.

- **`app.py`** — single-file Flask + paho-mqtt app (UI embedded). Auto-discovers
  nodes; the owning team's timer ticks live in the browser.
- **`deploy.sh`** — installs deps + a systemd service on the Pi.

## Deploy (over SSH — no git needed on the Pi)

The firmware repo isn't on a remote the Pi can clone, so we just copy the two
files over with `scp` and run the script on the Pi.

From this PC (PowerShell), replacing `<user>` with your Pi login:

```powershell
scp -r server <user>@192.168.88.129:~/airsoft-dashboard-src
ssh <user>@192.168.88.129
```

Then on the Pi:

```bash
cd airsoft-dashboard-src
bash deploy.sh
```

It prints the URL when done. Open it from any device on the field WiFi.

## Updating

Re-copy `app.py` and restart:

```powershell
scp server\app.py <user>@192.168.88.129:~/airsoft-dashboard/app.py
ssh <user>@192.168.88.129 'sudo systemctl restart airsoft-dashboard'
```

## Managing the service

```bash
sudo systemctl status airsoft-dashboard      # state
journalctl -u airsoft-dashboard -f           # live logs
sudo systemctl restart airsoft-dashboard     # restart
```

## Audio / voice packs

The dashboard speaks game events. Tap **Audio** in the header once (browser rule:
audio needs a user gesture) — that device then announces; others stay silent.
Plug the device into a powered speaker for field volume.

By default it uses the **browser's built-in voice (TTS)**. For nicer deployment
audio, drop **voice packs** of pre-rendered clips on the Pi and pick one from the
header dropdown. A pack is a folder of `.mp3` files:

```text
~/airsoft-dashboard/sounds/<pack-name>/      e.g. sounds/military_us_male/
```

Copy a pack over with scp, then refresh the page (it appears in the dropdown):

```powershell
scp -r military_us_male <user>@192.168.88.129:~/airsoft-dashboard/sounds/
```

**Any missing clip falls back to TTS**, so packs can be partial and filled in
over time. Clip filenames the dashboard looks for:

| File | Spoken as |
|------|-----------|
| `start.mp3` | "Game on." |
| `one_minute.mp3` | "One minute remaining." |
| `over_red.mp3` / `over_blue.mp3` / `over_tie.mp3` | "Time! Red/Blue wins." / "…tie." |
| `cap_<node>_<team>.mp3` | "Alpha taken by Red." — one per node × team |
| `audio_enabled.mp3` | "Audio enabled." (played when you tap Audio) |

`<node>` is the lowercase node id (alpha, bravo, …); `<team>` is `red` or `blue`.
The periodic state summary stays on TTS (too many phrasings to pre-render).

## Requirements

- Mosquitto running on the Pi with a listener on `:1883` (set up earlier).
- `python3-flask` and `python3-paho-mqtt` (installed by `deploy.sh` via apt —
  no pip/venv needed).

## Notes

- The dashboard talks to the broker at `localhost:1883`.
- Timers extrapolate between MQTT updates (firmware publishes game state on
  ownership change). A small later firmware tweak to publish state periodically
  would make them exact — and could be pushed to the nodes over OTA.
