# AGENTS.md — start here

Entry point for an AI coding agent picking up this project, especially on a new machine.
It covers the current state, the rules, machine-specific setup, hardware gotchas and the
backlog: things you can't easily tell from the code. It replaces the old HANDOFF.md.

_Last updated: 2026-10-17. Handed off from a Windows 11 dev PC to a Linux laptop._

## Read in this order

1. **This file**: current state, rules, setup, and corrections to the older docs.
2. [CLAUDE.md](CLAUDE.md): architecture, MQTT topic schema, and code conventions.
   Some hardware details in it are out of date (see "Stale docs" at the end).
3. [FIELD_DEPLOY.md](FIELD_DEPLOY.md): hands-on build, flash, and deploy runbook.
4. [WIRING.md](WIRING.md), [PROJECT_SPEC.md](PROJECT_SPEC.md), and [server/README.md](server/README.md) as needed.

---

## 1. What this is and where it stands

ESP32 "control point" boxes for indoor airsoft. Players hold a team button to capture a
point. Each box shows ownership on a WS2812B strip and an ST7789 LCD and reports over MQTT
to a central server, which runs a Flask live dashboard and the game modes.

- **Firmware** (`src/`, PlatformIO, Arduino-ESP32): `FIRMWARE_VERSION` **43** in [src/config.h](src/config.h).
- **Server** ([server/app.py](server/app.py), a single Flask + paho-mqtt + SSE file): `DASH_VERSION` **11**.
- **Deployed:** 3 control points in sealed enclosures, each powered by a 5 V / 5 A supply
  with no USB access, so they're updated over WiFi (OTA) only:
  - `alpha` = Pink Hallway
  - `bravo` = Kill House
  - `charlie` = Dark Room
  - Hostnames are `airsoft-controlpoint-<id>.local`.
  - All three run the real Field WiFi credentials (user confirmed on 2026-10-17).
- **Game modes that work:**
  - **Domination/King of the Hill:** cumulative per-team timers.
  - **Rush:** sequential bomb arming. The boxes act only as ownership sensors that don't
    know the game mode; the Rush state machine runs entirely in `server/app.py`.
- **Other features that work end to end:**
  - ST7789 LCD scoreboard, plus an optional OLED.
  - A 300-LED strip per node.
  - The live dashboard: game countdown, start/stop, reset and a results table.
  - Browser audio announcements, with a voice-pack system that falls back to TTS.
- **Not built yet:** flag and referee node types, Capture-All-Flags and CTF modes,
  arcade-button lamps, and SQLite match history. See the backlog (§9).

**LED behavior (since v25):**

| State | Strip shows |
|---|---|
| Boot | Self-test sweep: red, then green, then blue |
| Neutral, game stopped | White, breathing |
| Neutral, game running | Green |
| Being captured | Progress fill in the capturing team's color |
| Held | Comet-train chase in the owner's color |
| Paused or game over | Static, dim team color |

`setMaxPowerInVoltsAndMilliamps(5, 4500)` caps power and dims the strip automatically to
protect the 5 V / 5 A supply. The tunables (`CHASE_*`, `NUM_LEDS`, `LED_*`) are in config.h.

**The dashboard owns the game clock.** It runs the countdown and ends the round at 0. Nodes
treat the retained `airsoft/game/state` topic as the source of truth for run state and time
remaining.

---

## 2. Rules the user expects you to follow

- **Bump the version on every change:** add 1 to `FIRMWARE_VERSION` for firmware edits and to
  `DASH_VERSION` for dashboard edits. These are plain integers, not semver. Both are shown
  on-device or on-page, so the user can confirm a flash or deploy landed.
- **Commit once per major section of work**, not per tiny edit, and push to `origin main`
  (`ssh://git@github.com/imikejackson/AirsoftGameControl`). End each commit message with your
  `Co-Authored-By:` trailer.
- **Never commit secrets.** `src/secrets.h` (WiFi and OTA passwords) and `field-guide.svg`
  (contains the WiFi password) are gitignored on purpose. Get the real values from the user,
  never from git history.
- **Main loops never block:** use `millis()` timing, no `delay()`. Local node state is
  authoritative; the network only reports it.
- **Don't full-erase a node's flash.** It wipes `node_id` in NVS, and the box comes back as
  `alpha` and publishes under the wrong MQTT topic. A brand-new bench board also starts as
  `alpha`, so give it its own ID with the serial `nodeid <id>` command before it reaches the
  broker. To fix WiFi, use the serial `wifi`, `preset`, or `nodeid` commands instead of erasing.

---

## 3. First-time setup on a new machine

None of these settings travel with the repo:

1. **`src/secrets.h`:** run `cp src/secrets.example.h src/secrets.h`, then fill in the real
   passwords (ask the user). It defines `DEFAULT_WIFI_SSID`, `DEFAULT_WIFI_PASS`,
   `WIFI_PRESETS`, and `OTA_PASSWORD`. The presets are:
   - Slot 0 = **Field** ("MKAirsoft Middletown"), RED button.
   - Slot 1 = **Ground Control** (home/dev), BLUE button.

   These values only fill the node's NVS storage on first boot. Deployed nodes keep their
   credentials in NVS.
2. **OTA callback IP:** [platformio.ini](platformio.ini) `[env:esp32dev_ota]` hardcodes
   `--host_ip=192.168.4.61` (an older Mac dev box). Set it to **this machine's** LAN IP on
   the same network as the nodes (`ip addr`, `ipconfig`, or `ipconfig getifaddr en0`).
   Otherwise espota fails with "No response from the ESP". The setting exists because
   espota listens on all interfaces and can tell the ESP to call back on an address it can't
   reach.
3. **PlatformIO:** if `pio` isn't on PATH, use the full path:
   - Linux/macOS: `~/.platformio/penv/bin/pio`
   - Windows: `%USERPROFILE%\.platformio\penv\Scripts\pio.exe`
4. **USB serial:**
   - The boards use CH340K USB chips (`VID:PID=1A86:7522`), so the CH340 driver is needed
     on Windows and macOS.
   - Port names (COM numbers, `/dev/ttyUSBx`) change when boards are replugged. To identify
     a node, reset it and read the serial banner (`node type`, node ID, `connected as ...`).
   - On the old PC, a device with `VID:PID=29EA:1001` also showed up on some ports. It
     isn't a node; ignore it.
   - **Linux:** your user must be in the `dialout` group to open `/dev/ttyUSB*`. Run
     `sudo usermod -aG dialout $USER`, then log out and back in.
5. **Windows only:** add a Windows Firewall inbound-allow rule for PlatformIO's
   `penv\Scripts\python.exe`, or OTA times out (run once, elevated):
   `New-NetFirewallRule -DisplayName "PlatformIO espota" -Direction Inbound -Program "<path>\.platformio\penv\Scripts\python.exe" -Action Allow`.
   PowerShell also breaks multi-line commit messages, so write the message to a file and use
   `git commit -F <file>`.
6. **GitHub push auth:** the old PC used a repo-local `core.sshCommand` with a deploy key
   that did not come with the clone. On this machine, use your own GitHub credentials.

---

## 4. Build, flash, OTA, and server deploy

```
pio run -e esp32dev                                    # build control-point firmware
pio run -e esp32dev -t upload --upload-port <COMx|/dev/ttyUSBx>        # USB (bench)
pio run -e esp32dev_ota -t upload --upload-port airsoft-controlpoint-<id>.local   # OTA (deployed)
scp server/app.py airsoft@airsoft-pi.local:~/airsoft-dashboard/app.py
ssh airsoft@airsoft-pi.local 'sudo systemctl restart airsoft-dashboard'
```

- **OTA can drop mid-transfer** on weak WiFi or power, stopping at a random percentage. Just
  retry; it usually completes within a few tries. A retry loop that stops on "SUCCESS" works.
- **OTA device side:** ArduinoOTA listens on **port 3232** and advertises
  `<hostname>.local`. If `OTA_PASSWORD` is set in secrets.h, add
  `--upload-flags --auth=<password>` to the upload command.
- **OTA only works on a node that is already online.** A bricked or offline node needs USB
  recovery: open the box, plug in a cable, and flash over USB.
- **Target nodes by their `.local` names.** Their DHCP IPs move.
- **The server has no git.** Deploy `app.py` with scp, as above.

**PlatformIO environments ([platformio.ini](platformio.ini)):**
- `esp32dev`, `controlpoint`, `flag`, and `referee` each build one node type, selected with
  `-D NODE_TYPE_IS_*`. `esp32dev` is the same as `controlpoint`.
- `esp32dev_ota` builds the same control-point firmware but uploads it over WiFi with espota.
- TFT_eSPI is configured entirely through `build_flags` (ST7789 driver, pins, fonts). Don't
  add a `User_Setup.h`.

---

## 5. Network map

| Thing | Hostname (mDNS) | Notes |
|---|---|---|
| Control point alpha | `airsoft-controlpoint-alpha.local` | DHCP IP changes, so use the hostname |
| Control point bravo | `airsoft-controlpoint-bravo.local` | Same |
| Control point charlie | `airsoft-controlpoint-charlie.local` | Same |
| Central server / broker | `airsoft-pi.local` | Mosquitto on :1883, dashboard on :8080 |

- **Node IPs move:** they have been .36/.37/.39 and later .49/.50/.52. Always use the `.local`
  hostnames. DHCP reservations by MAC address would be an optional fix.
- The MQTT topic schema, node types, and IDs are in [CLAUDE.md](CLAUDE.md).

---

## 6. Hardware (gotchas first, most expensive first)

- **WiFi `reason 201` (NO_AP_FOUND):** the ESP32-WROOM-**32U** has no PCB antenna, so first
  check that the IPEX antenna is attached. A 5 GHz-only SSID or a truncated SSID causes the
  same error.
- **Boot hangs right after printing `node type:`:** the USB power is too weak (old hubs), and
  the board browns out at `WiFi.mode()`. Use a direct or powered port, or the 5 V supply.
  This differs from the antenna fault: with a missing antenna, WiFi starts but finds no
  access point.
- **All WS2812s, including the status pixel on GPIO 2, go through FastLED.** Don't use
  `neopixelWrite`. Mixing it with FastLED's RMT driver stops FastLED from binding the strip
  pin.
- **"GPIO 227 invalid pin" at boot is harmless.** It comes from TFT_eSPI's LCD setup, not
  the LEDs.

**Per control-point node:**
- **ESP32:** Lonely Binary ESP32-WROOM-32U with a CH340K USB chip and USB-C. It needs its
  external IPEX antenna.
- **LED strip:** WS2812B, **300 LEDs**, data on **GPIO 5**. It runs off the external 5 V
  supply and shares ground with the ESP32.
  - At full white, each LED draws about 60 mA. The 5 A supply only covers about 80 LEDs at
    full white, so the FastLED power cap is what keeps the 300-LED strip safe.
  - On long runs, inject 5 V at both ends to avoid dimming at the far end.
- **Displays:** **ST7789 2" LCD** (SPI) as the scoreboard. An **SSD1306 OLED** (I2C) is
  optional; the firmware checks for it at boot.
- **Buttons:** simple 2-terminal buttons, wired active-low to **GPIO 25 (red)** and
  **GPIO 26 (blue)** with `INPUT_PULLUP`. An optional reset button is on **GPIO 27**. The
  full pin table is in [CLAUDE.md](CLAUDE.md) and [WIRING.md](WIRING.md).

**Power (final build):**
- One 5 V / 5 A supply feeds both the strip's injection point and the ESP32.
- Power the ESP32 through the **`5V`/`VIN` pin** or **USB-C VBUS**. The USB-C option uses a
  chopped USB-A-to-C cable: red is 5 V, black is GND, and the data wires are unused.
- **Never** power it through the `3V3` pin, and don't connect two power sources at once.

**Adafruit 1190 arcade buttons (bought, not wired yet):**
- 60 mm "Large Arcade Button w/ LED" with 4 contacts.
- Two contacts are a normally-open microswitch (COM/NO), wired like the current buttons.
- The other two are an LED whose built-in resistor is rated up to 12 V, so it is dim on 5 V.
- The plan is firmware-controlled lamps on GPIO 32/33 (see backlog).

---

## 7. Central server

- **Hardware:** an HP All-in-One 22-dd0123w (Pentium Silver J5040, 4 GB RAM, SSD) running
  **Ubuntu Server 26.04 LTS**, headless over SSH. It replaced the original Raspberry Pi Zero
  2 W.
  - Its screen is broken and removed, but it **won't POST (7 blinks) unless the display
    backlight cable stays connected**, so leave the dead panel attached.
  - Its HDMI port is an output, so an external monitor works.
- **Hostname stays `airsoft-pi`**, so nodes find the broker at `airsoft-pi.local` with no
  firmware change. `avahi-daemon` provides the `.local` name.
- **Mosquitto 2.x** needs `listener 1883` and `allow_anonymous true`.
- **Server code is in [server/](server/):**
  - `app.py`: the Flask + paho-mqtt + SSE dashboard, which also runs the game clock.
  - `deploy.sh`: installs `mosquitto python3-flask python3-paho-mqtt` with apt, sets up the
    systemd service, and creates the sound-pack folders.
  - `README.md`: deploying with scp.
- **Ubuntu 26.04 enforces PEP 668,** so install Python packages with apt or in a venv, never
  with system `pip`.

---

## 8. Stale docs and conflicting facts (verify before relying on them)

- **Displays:** CLAUDE.md describes TM1637 7-segment displays and a 60-LED/m 2 m strip.
  The real build uses an **ST7789 LCD**, an optional SSD1306 OLED, and **300 LEDs**. The
  `PIN_DISP_*` defines in config.h are legacy.
- **Server:** CLAUDE.md says Raspberry Pi Zero 2 W, and server/README.md uses the old Pi IP
  `192.168.88.129`. The real server is the HP box at `airsoft-pi.local` (§7).
- **Network addressing:** the older docs say the dev LAN is `192.168.88.x`. A 2026-09-12
  commit says Ground Control now hands out **`192.168.4.x`**, with the broker at `.58`.
  Use mDNS names, and confirm actual addresses with the user.
- **Field WiFi:** older notes mention a placeholder Field preset on the deployed boxes and a
  workaround using a spare router that broadcasts "Ground Control". Both are out of date: the
  boxes have been reflashed with the real Field credentials.
- **Rush rules:** the server implements defuse as **pause** (the attacker's arm time resumes)
  and has a referee-set sudden-death defuse hold (`RUSH_DEFUSE_MAX` = 5 s). Treat both as
  current behavior unless the user says otherwise.

---

## 9. Backlog (agreed but not built)

1. **Illuminated arcade-button lamps** (Adafruit 1190):
   - Add `PIN_LAMP_RED`/`PIN_LAMP_BLUE` on GPIO 32/33.
   - Drive each lamp through a low-side MOSFET.
   - In firmware, light each button in its team color and pulse it on capture.
   - The lamps are dim on 5 V; add a 12 V lamp supply for full brightness.
2. **Flag and referee node types** (`game_flag.cpp`, `game_referee.cpp`). They share about
   80% of the firmware and add their own game logic on top, per CLAUDE.md. Flags track
   ownership only, with no timers.
3. **Capture-All-Flags and Classic CTF modes.**
4. **MQTT `set_wifi` command plus a dashboard control,** for re-pointing sealed boxes. The
   serial `wifi <ssid> <pass>` command already exists in network.cpp, but it needs a USB
   cable, which sealed boxes don't have.
5. **Field WiFi hardware.** The Pi's onboard antenna was too weak to act as the access
   point. The decision is a **dedicated router/AP with external antennas**, with the server
   connected by Ethernet. Running OPNsense on the HP box was considered and rejected: it is
   a router/firewall OS with poor WiFi access-point support, and it doesn't host the app
   stack well.
6. **Voice-pack audio clips:** the support for them exists (a manifest plus TTS fallback).
   Generate the clips and scp them to the server.
7. **SQLite match history.**
8. **WIRING.md:** document the USB-C power pigtail and the arcade-button pinout.
