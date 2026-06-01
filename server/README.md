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

## Requirements

- Mosquitto running on the Pi with a listener on `:1883` (set up earlier).
- `python3-flask` and `python3-paho-mqtt` (installed by `deploy.sh` via apt —
  no pip/venv needed).

## Notes

- The dashboard talks to the broker at `localhost:1883`.
- Timers extrapolate between MQTT updates (firmware publishes game state on
  ownership change). A small later firmware tweak to publish state periodically
  would make them exact — and could be pushed to the nodes over OTA.
