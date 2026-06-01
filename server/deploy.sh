#!/usr/bin/env bash
#
# deploy.sh — install the Airsoft dashboard on the Raspberry Pi.
#
# Run this ON THE PI (after copying the server/ folder over with scp — no git
# required). It installs the Python deps from apt, drops app.py in place, and
# registers a systemd service that starts on boot and restarts on failure.
#
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/airsoft-dashboard"
RUN_USER="$(id -un)"

echo "[deploy] installing dependencies (python3-flask, python3-paho-mqtt)..."
sudo apt-get update -qq
sudo apt-get install -y python3-flask python3-paho-mqtt

echo "[deploy] installing app to $APP_DIR ..."
mkdir -p "$APP_DIR"
mkdir -p "$APP_DIR/sounds"     # drop voice-pack folders here (one dir per pack)
cp "$SRC/app.py" "$APP_DIR/app.py"
# Copy any bundled voice packs alongside the script (optional).
if [ -d "$SRC/sounds" ]; then cp -r "$SRC/sounds/." "$APP_DIR/sounds/"; fi

echo "[deploy] writing systemd service ..."
sudo tee /etc/systemd/system/airsoft-dashboard.service >/dev/null <<EOF
[Unit]
Description=Airsoft Control Point Dashboard
After=network-online.target mosquitto.service
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 $APP_DIR/app.py
WorkingDirectory=$APP_DIR
Restart=always
RestartSec=3
User=$RUN_USER

[Install]
WantedBy=multi-user.target
EOF

echo "[deploy] enabling + starting service ..."
sudo systemctl daemon-reload
sudo systemctl enable --now airsoft-dashboard
sleep 1
sudo systemctl --no-pager --lines=0 status airsoft-dashboard || true

IP="$(hostname -I | awk '{print $1}')"
echo
echo "[deploy] Dashboard is live:  http://${IP}:8080   (or http://airsoft-pi.local:8080)"
echo "[deploy] Follow logs with:   journalctl -u airsoft-dashboard -f"
echo "[deploy] Update later: re-copy app.py and run 'sudo systemctl restart airsoft-dashboard'"
