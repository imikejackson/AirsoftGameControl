# Field Deploy Runbook — build & flash from a laptop

Goal: from a laptop **at the field**, set up the toolchain, bake the **real field
WiFi** into the firmware, and flash the nodes (USB or OTA) — plus deploy the
dashboard. Read [CLAUDE.md](CLAUDE.md) for architecture; this is the hands-on
deploy procedure.

_Current state: firmware **v43**, dashboard **v11**, all pushed to
`github.com/imikejackson/AirsoftGameControl`. Nodes: 3 control points —
alpha (Pink Hallway), bravo (Kill House), charlie (Dark Room)._

---

## 0. Network presets
`WIFI_PRESETS` slot 0 is **Field** / **RED** (`MKAirsoft Middletown`), and slot 1
is **Ground Control** / **BLUE** (the home/dev network). The deployed boxes
already have both baked in. At the field, power-cycle a box and press **RED** at
the **SELECT WiFi** screen, or let it time out to the last-used network.

---

## 1. Laptop prerequisites (one-time)
- **VS Code + PlatformIO IDE extension** (easiest — gives you `pio` and a GUI),
  or headless: `pip install platformio`.
- **Git**.
- **CH340 USB-serial driver** (the ESP32 boards use a CH340K). Without it the
  board won't enumerate a COM port.
- A **USB-C data cable** (not charge-only) and a **direct USB port** (a weak hub
  can brown the board out mid-boot — see gotchas).

Verify: `pio --version` and `git --version` both print.

## 2. Get the code
```
git clone https://github.com/imikejackson/AirsoftGameControl.git
cd AirsoftGameControl
```
(HTTPS + your GitHub login/token is simplest on a fresh laptop.)

## 3. ⚑ Create secrets.h with the REAL field WiFi
`src/secrets.h` is gitignored, so a fresh clone doesn't have it. Create it from
the template and set the real networks:
```
cp src/secrets.example.h src/secrets.h        # (Windows: copy in the editor)
```
Edit `src/secrets.h` so `WIFI_PRESETS` slot 0 is the **actual field AP**:
```c
#define DEFAULT_WIFI_SSID  "MKAirsoft Middletown"
#define DEFAULT_WIFI_PASS  "<FIELD PASSWORD>"

#define WIFI_PRESETS { \
  { "Field",          DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASS }, \
  { "Ground Control", "Ground Control",  "<HOME PASSWORD>" }, \
}
```
- Slot 0 (Field) = **RED**, slot 1 (Ground Control) = **BLUE**.
- SSIDs/passwords are case-sensitive; keep the quotes.
- Bump `FIRMWARE_VERSION` in `src/config.h` by 1 (it shows on the LCD, so you can
  confirm the flash took).

## 4. Build
```
pio run -e esp32dev
```

## 5. Flash the nodes
Pick whichever fits what you can reach at the field.

### 5a. USB (most reliable at the field)
Node IDs live in NVS, so the same binary is fine for all three — each keeps its
own identity. **Do NOT full-erase** (that wipes `node_id` and the box comes back
as the default "alpha").
```
pio device list                                   # find the CH340K COM port
pio run -e esp32dev -t upload --upload-port COM<x>
```
Repeat for each node. After it reboots, on the LCD **SELECT WiFi** menu press
**RED** (Field) to join — or let it time out to the last-used network.

### 5b. Serial reprovision — NO rebuild (fastest if you just need WiFi changed)
The firmware already takes runtime WiFi commands over serial; you don't have to
build/flash at all for a WiFi fix:
```
pio device monitor -p COM<x> -b 115200
```
then type (quotes handle spaces):
```
wifi "<REAL FIELD SSID>" <password>
```
It saves to NVS and reconnects immediately, and it **sticks** (custom creds
aren't overwritten by the preset re-sync). Other serial commands: `presets`,
`preset <n>`, `netstatus`, `nodeid <id>`, `mqtt <host> <port>`, `reset`.
⚠️ On later boots, **let the WiFi picker time out** — pressing a preset button
would overwrite these custom creds with a preset.

### 5c. OTA (only once a node is on WiFi and on the SAME network as the laptop)
```
pio run -e esp32dev_ota -t upload --upload-port airsoft-controlpoint-<name>.local
```
**Must set `--host_ip` to the LAPTOP's IP on the field network** or espota times
out ("No response from the ESP") — the callback can pick a wrong NIC otherwise.
Either edit `platformio.ini` `[env:esp32dev_ota]` `upload_flags = --host_ip=<laptop-ip>`
(currently hardcoded to the home dev PC's `192.168.88.201` — change it) or pass
`--upload-flags "--host_ip=<laptop-ip>"`. Find the laptop IP with `ipconfig`.
OTA is flaky on weak signal — just retry; it usually completes in a few tries.

## 6. Deploy the dashboard (server)
Server = `airsoft-pi.local`, app at `~/airsoft-dashboard/app.py`, systemd
service `airsoft-dashboard`, dashboard on **:8080**, Mosquitto on **:1883**.
```
scp server/app.py airsoft@airsoft-pi.local:~/airsoft-dashboard/app.py
ssh airsoft@airsoft-pi.local 'sudo systemctl restart airsoft-dashboard'
```
Notes:
- `sudo` on the server may need a password (interactive). If restarting non-
  interactively, kill the process and let systemd relaunch it (Restart=always):
  `ssh airsoft@airsoft-pi.local 'pkill -f "[a]irsoft-dashboard/app.py"'`.
- Bump `DASH_VERSION` in `server/app.py` per change (shown in the page header).
- Verify: open `http://airsoft-pi.local:8080` (or `http://<server-ip>:8080`).

## 7. Push your changes back
```
git add -A && git commit -m "…" && git push origin main
```
(On the laptop, authenticate to GitHub with your own login/token.)

---

## Gotchas (hard-won)
- **Antenna:** the ESP32-WROOM-**32U** needs its IPEX antenna seated, or WiFi
  fails `reason 201 (NO_AP_FOUND)` — same symptom as wrong creds.
- **USB power:** a marginal/hub port browns the board out at `WiFi.mode()`; it
  hangs right after printing `node type:`. Use a direct/powered port.
- **Truncated SSID:** an SSID with spaces typed unquoted over serial used to be
  cut at the first space (fixed) — use quotes to be safe.
- **Full chip erase wipes `node_id`** → box boots as "alpha" and publishes under
  the wrong topic. Re-set with `nodeid <id>` if you ever erase.
- **Version bump discipline:** +1 `FIRMWARE_VERSION` / `DASH_VERSION` every change
  so you can confirm a flash/deploy actually landed (both are shown on-screen).
- **Sleep:** boxes blank + run a rainbow after `SLEEP_TIMEOUT_MS` (10 min) idle.
- **Rush WiFi note:** getting the boxes online at the field only needs the WiFi
  preset (steps 3–5); the game logic is already deployed.
