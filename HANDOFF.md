# Project Handoff — Airsoft Control Point System

**Purpose:** everything a fresh assistant session (on a *different* computer) needs to
continue this project. Read [CLAUDE.md](CLAUDE.md) first for the architecture and
conventions; this file captures **current state, environment-specific setup, hardware
gotchas, and the backlog** that aren't obvious from the code alone.

_Last updated: 2026-08-29._

---

## 1. Where the project is right now

- **Firmware: v43** (`FIRMWARE_VERSION` in [src/config.h](src/config.h)). Deployed to all
  three control points over OTA.
- **Dashboard: DASH_VERSION 11** ([server/app.py](server/app.py)).
- **3 control points built and deployed in final enclosures**, powered from a 5 V / 5 A
  supply (no USB in the box), reachable only over WiFi/OTA:
  - `alpha`, `bravo`, `charlie` — hostnames `airsoft-controlpoint-<name>.local`.
- **What works end-to-end:** button capture (King-of-the-Hill), cumulative per-team timers,
  ST7789 LCD scoreboard, optional OLED, **300-LED WS2812B strip** per node (FastLED), MQTT
  reporting to the broker, live web dashboard with game countdown / start-stop / reset /
  results table, and browser audio announcements + a voice-pack system (TTS fallback).
- **LED behavior (v25):** boot self-test (R→G→B sweep); neutral = **white** breathing when
  the game is stopped, **green** when running; capturing = progress fill in the capturing
  team's color; held = **comet-train chase** in the owner's color; paused/over = static dim
  team color. FastLED power cap (`setMaxPowerInVoltsAndMilliamps(5, 4500)`) auto-dims to
  protect the 5 V / 5 A supply. Tunables (`CHASE_*`, `NUM_LEDS`, `LED_*`) in config.h.

### Git
- Remote: `origin` = `ssh://git@github.com/imikejackson/AirsoftGameControl`, branch `main`.
- Convention: **commit per major section**; bump `FIRMWARE_VERSION` (+1) on every firmware
  change and `DASH_VERSION` (+1) on every dashboard change — both are shown on-device/on-page
  so you can confirm an OTA/deploy actually took.
- End commit messages with the `Co-Authored-By: Claude ...` trailer.

---

## 2. ⚠️ Environment-specific setup (WILL differ on a new computer)

The previous dev machine was Windows 11 + PowerShell. **These values are machine-specific and
must be re-established on any new computer:**

1. **`secrets.h` is gitignored and NOT in the repo.** Copy the template and fill in real
   values (get them from the user or the old machine's `src/secrets.h`):
   ```
   cp src/secrets.example.h src/secrets.h
   ```
   It defines `DEFAULT_WIFI_SSID`, `DEFAULT_WIFI_PASS`, `OTA_PASSWORD`. The two presets are
   **"MKAirsoft Middletown"** (Field, **RED**, slot 0) and **"Ground Control"** (home/dev,
   **BLUE**, slot 1); passwords live only in the gitignored `secrets.h`. These only *seed* NVS
   on first boot; deployed nodes hold their creds in NVS.

2. **OTA callback IP is hardcoded to the OLD PC.** [platformio.ini](platformio.ini) `env:esp32dev_ota`
   sets `upload_flags = --host_ip=192.168.88.201`. **Change this to the new PC's IP on the
   192.168.88.x LAN** (`ipconfig` / `ip addr`), or OTA will time out with "No response from
   the ESP". This exists because espota binds `0.0.0.0` and can advertise an unreachable NIC.

3. **Windows Firewall must allow the PlatformIO python inbound** for OTA (only on Windows):
   `New-NetFirewallRule -DisplayName "PlatformIO espota" -Direction Inbound -Program "<path>\.platformio\penv\Scripts\python.exe" -Action Allow` (run elevated, once).

4. **`pio` was not on PATH** on the old machine; commands used the full path
   `"$env:USERPROFILE\.platformio\penv\Scripts\pio.exe"`. On a new machine, install PlatformIO
   (VS Code extension or `pip install platformio`) and use `pio` directly if it's on PATH.

5. **git** was at `C:\Applications\git\bin\git.exe` on the old machine. Use whatever `git` is
   on the new machine. (PowerShell multi-line commit messages mis-tokenize — write the message
   to a file with ASCII encoding and `git commit -F <file>`; not needed on bash.)

6. **COM ports are not stable.** USB-serial adapters are CH340K (`VID:PID=1A86:7522`). Ports
   renumber on replug. Identify a node by resetting it and reading the serial banner
   (`node type`, node id, `connected as ...`). There is also a non-node device on some ports
   (`VID:PID=29EA:1001`) — ignore it.

---

## 3. Network map

| Thing | Hostname (mDNS) | Notes |
|---|---|---|
| Control point alpha | `airsoft-controlpoint-alpha.local` | DHCP IP changes — resolve by hostname |
| Control point bravo | `airsoft-controlpoint-bravo.local` | " |
| Control point charlie | `airsoft-controlpoint-charlie.local` | " |
| Central server / broker | `airsoft-pi.local` | Mosquitto :1883, dashboard :8080 |

- **Node IPs are DHCP and DO move** (they've been on .36/.37/.39, then .49/.50/.52). **Always
  target `.local` hostnames, not hardcoded IPs.** (Optional: set DHCP reservations by MAC.)
- MQTT topic schema, node types, and IDs are documented in [CLAUDE.md](CLAUDE.md).
- The two WiFi presets are **"MKAirsoft Middletown"** (Field, **RED**, slot 0) and
  **"Ground Control"** (home/dev, **BLUE**, slot 1); passwords live only in the gitignored
  `secrets.h`.

---

## 4. Build / flash / OTA

```
# Build (control point)
pio run -e esp32dev

# USB flash (bench, when a node is cabled)
pio run -e esp32dev -t upload --upload-port COM<x>

# OTA flash (deployed nodes — the normal path now)
pio run -e esp32dev_ota -t upload --upload-port airsoft-controlpoint-<name>.local
#   requires --host_ip in platformio.ini set to THIS PC (see section 2)
```

- **OTA is flaky** on marginal WiFi/power: a ~930 KB image can drop mid-transfer at a random
  percentage. **Retry** — it usually completes within a few attempts. A retry loop that stops
  on "SUCCESS" is the pragmatic approach. Better signal/power = first-try success.
- OTA device side: ArduinoOTA on **port 3232**, advertised as `<hostname>.local`. Set
  `OTA_PASSWORD` in secrets.h before real deployment (add `--auth=<pw>` to upload flags).
- ArduinoOTA / mDNS only works while the node is already on the network; a bricked/offline
  node needs USB recovery (open box, cable in, flash over USB).

### PlatformIO environments ([platformio.ini](platformio.ini))
- `esp32dev` / `controlpoint` / `flag` / `referee` — one per node type via `-D NODE_TYPE_IS_*`.
- `esp32dev_ota` — same control-point firmware, pushed via espota over WiFi.
- TFT_eSPI is configured entirely through `build_flags` (ST7789, pins, fonts) — do not add a
  User_Setup.

---

## 5. Hardware summary & gotchas (hard-won — read before touching hardware)

**Per control-point node:**
- ESP32 dev board — **Lonely Binary ESP32-WROOM-32U, CH340K USB, USB-C**. The **-32U needs its
  external IPEX antenna attached** — if it's detached you get WiFi `reason 201 (NO_AP_FOUND)`.
- **WS2812B strip, 300 LEDs**, data on **GPIO 5**, powered by the external 5 V supply (common
  ground with the ESP32). ~60 mA/LED at full white → the 5 A supply only covers ~80 LEDs at
  full white, so the **FastLED power cap is what keeps 300 LEDs safe** (it auto-dims). For a
  long run, inject 5 V at both ends to avoid far-end dimming/voltage drop.
- **ST7789 2" LCD** (SPI) as the scoreboard; **SSD1306 OLED** (I2C) optional (probed at boot).
- Onboard status RGB (WS2812 on **GPIO 2**) — driven **through FastLED**, NOT `neopixelWrite`.
  Mixing FastLED's RMT driver with the core's `neopixelWrite` makes FastLED fail to bind the
  strip pin (you'll see a bogus "GPIO 227 / invalid pin" error). All WS2812s go through FastLED.
- The **"GPIO 227 invalid pin" line at boot is harmless** — it comes from TFT_eSPI LCD init, not
  the LEDs. Ignore it.
- Buttons: currently simple 2-terminal, wired active-low to **GPIO 25 (red) / 26 (blue)** with
  `INPUT_PULLUP`, optional reset on **27**. Full pin table in [CLAUDE.md](CLAUDE.md) /
  [WIRING.md](WIRING.md).

**Power (final build):** one 5 V / 5 A supply feeds both the strip's injection point and the
ESP32. Power the ESP32 via the **`5V`/`VIN` pin OR the USB-C VBUS** (a chopped USB-A→C cable:
red=5 V, black=GND, data unused) — **never the `3V3` pin**, and don't feed two sources at once.

**⚠️ Marginal USB power = boot hang.** On a weak USB hub/port the node hangs right after
printing `node type:` — that's `WiFi.mode(WIFI_STA)` browning out. Use a direct/powered port or
the 5 V supply. (Different from the antenna fault above, which inits WiFi fine then can't find AP.)

**Adafruit 1190 arcade buttons (acquired, NOT yet wired):** "Large Arcade Button w/ LED, 60 mm".
4 contacts = a normally-open **microswitch** (COM/NO — wire like the current buttons) + an **LED**
whose built-in resistor is rated **up to 12 V** (so it's dim on 5 V). Plan for firmware-controlled
lamps via low-side MOSFET on **GPIO 32 (red) / 33 (blue)** — see backlog.

---

## 6. Central server (MIGRATION IN PROGRESS)

- **Was:** Raspberry Pi Zero 2 W (`airsoft-pi`, `192.168.88.129`), Mosquitto + Flask + audio.
- **Now migrating to:** an **HP All-in-One 22-dd0123w** (Intel **Pentium Silver J5040**, 4 GB
  RAM, SSD) stripped of its broken screen, running **Ubuntu Server 26.04 LTS**.
  - **It 7-blinks and won't POST unless the display *backlight cable* stays connected** — leave
    the (dead) panel electrically connected. HDMI is an **output**, so an external monitor works.
  - **Set its hostname to `airsoft-pi`** so nodes keep finding the broker at `airsoft-pi.local`
    with zero reprovisioning. Install `avahi-daemon` for `.local`.
  - Enable OpenSSH during install; the box then runs headless.
- **Server code:** [server/](server/) — `app.py` (Flask + paho-mqtt + SSE dashboard, game-clock
  authority), `deploy.sh` (apt: `mosquitto python3-flask python3-paho-mqtt`, systemd service,
  sound-pack dirs), `README.md` (deploy over scp — there was no git on the Pi). Ubuntu 26.04
  enforces PEP 668, so stick to apt packages (or a venv) — not system `pip`.
- Dashboard is the **game-clock authority**: it owns the countdown, ticks it, and ends the round
  at 0. Nodes treat `airsoft/game/state` (retained) as authoritative for run state + remaining.

---

## 7. Backlog / next steps (agreed but not built)

1. **WiFi management enhancement.** Nodes already carry both baked-in presets: Field in slot 0
   (RED) and Ground Control in slot 1 (BLUE). A future enhancement could add an MQTT `set_wifi`
   command + dashboard control for over-the-air changes. Serial `wifi <ssid> <pass>` already
   exists (network.cpp) but is impractical on sealed boxes.
2. **Field WiFi hardware.** The Pi's onboard antenna was too weak to be the AP. Decision: use a
   **dedicated router/AP with external antennas**; the server (HP box) plugs in via Ethernet.
   (Considered OPNsense on the HP box and rejected — it's a router/firewall OS, poor WiFi-AP
   support, and doesn't host the app stack well.)
3. **Illuminated arcade-button lamps** (Adafruit 1190) — add `PIN_LAMP_RED`/`PIN_LAMP_BLUE`
   (GPIO 32/33), low-side MOSFET drive, firmware to light each button in its team color / pulse
   on capture. Dim on 5 V; add a 12 V lamp supply for full brightness.
4. **Document WIRING.md** with the USB-C power pigtail and the arcade-button pinout.
5. **New node types:** flag nodes (ownership only, no timers) and referee buttons — ~80% shared
   firmware, layered game logic (`game_flag.cpp`, `game_referee.cpp` per CLAUDE.md).
6. **Game modes** beyond King-of-the-Hill: Capture-All-Flags, Classic CTF.
7. **Voice packs:** the infrastructure exists (manifest + TTS fallback); generate the AI-voice
   clips and scp them to the server.

---

## 8. Quick "gotcha" checklist

- [ ] Created `src/secrets.h` from the example with real WiFi creds.
- [ ] Updated `--host_ip` in platformio.ini to the new PC's LAN IP.
- [ ] (Windows) firewall allows the PlatformIO python inbound.
- [ ] Target nodes by `.local` hostname, not stale IPs.
- [ ] Antenna attached on any -32U node (else reason 201).
- [ ] Adequate power when flashing over USB (else boot hang at `node type:`).
- [ ] OTA fails randomly mid-transfer → just retry.
- [ ] Bump `FIRMWARE_VERSION` / `DASH_VERSION` and commit per section.
- [ ] New server keeps hostname `airsoft-pi`; backlight cable stays connected.
