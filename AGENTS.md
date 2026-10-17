# AGENTS.md — start here

Entry point for an AI coding agent picking up this project on a new machine.
_Last updated: 2026-10-17 (handed off from a Windows 11 dev PC)._

## Read in this order

1. **This file**: current state, rules, and corrections to the older docs.
2. [CLAUDE.md](CLAUDE.md): architecture, MQTT topic schema, and code conventions.
   Some hardware details in it are out of date (see "Stale docs" below).
3. [HANDOFF.md](HANDOFF.md): detailed hardware gotchas, the network map, and the backlog
   (dated 2026-08-29).
4. [FIELD_DEPLOY.md](FIELD_DEPLOY.md): hands-on build, flash, and deploy runbook.
5. [WIRING.md](WIRING.md), [PROJECT_SPEC.md](PROJECT_SPEC.md), and [server/README.md](server/README.md) as needed.

## What this is

ESP32 "control point" boxes for indoor airsoft. Players hold a team button to capture a
point. Each box shows ownership on a WS2812B strip and an ST7789 LCD and reports over MQTT
to a central server, which runs a Flask live dashboard and the game modes.

- **Firmware** (`src/`, PlatformIO, Arduino-ESP32): `FIRMWARE_VERSION` **43** in [src/config.h](src/config.h).
- **Server** (`server/app.py`, a single Flask + paho-mqtt + SSE file): `DASH_VERSION` **11**.
- **Deployed:** 3 control points in sealed enclosures, updated over WiFi (OTA) only:
  - `alpha` = Pink Hallway
  - `bravo` = Kill House
  - `charlie` = Dark Room
  - Hostnames are `airsoft-controlpoint-<id>.local`.
- **Game modes that work:** Domination/King of the Hill (cumulative per-team timers) and
  **Rush** (sequential bomb arming). In Rush, the boxes are mode-agnostic ownership sensors;
  the Rush state machine runs entirely in `server/app.py`.
- **Not built yet:** flag and referee node types, Capture-All-Flags and CTF modes,
  arcade-button lamps, and SQLite match history. See HANDOFF.md §7.

## Rules the user expects you to follow

- **Bump the version on every change:** add 1 to `FIRMWARE_VERSION` for firmware edits and to
  `DASH_VERSION` for dashboard edits. These are plain integers, not semver. Both are shown
  on-device or on-page, so the user can confirm a flash or deploy landed.
- **Commit once per major section of work**, not per tiny edit, and push to `origin main`
  (`github.com/imikejackson/AirsoftGameControl`). End each commit message with your
  `Co-Authored-By:` trailer.
- **Never commit secrets.** `src/secrets.h` (WiFi and OTA passwords) and `field-guide.svg`
  (contains the WiFi password) are gitignored on purpose. Get the real values from the user,
  never from git history.
- **Main loops never block:** use `millis()` timing, no `delay()`. Local node state is
  authoritative; the network only reports it.
- **Don't full-erase a node's flash.** It wipes `node_id` in NVS, and the box comes back as
  `alpha` and publishes under the wrong MQTT topic. To fix WiFi, use the serial `wifi`,
  `preset`, or `nodeid` commands instead.

## First-time setup on a new machine

None of these settings travel with the repo:

1. **`src/secrets.h`:** run `cp src/secrets.example.h src/secrets.h`, then fill in the real
   passwords (ask the user). The presets are:
   - Slot 0 = **Field** ("MKAirsoft Middletown"), RED button.
   - Slot 1 = **Ground Control** (home), BLUE button.
2. **OTA callback IP:** [platformio.ini](platformio.ini) `[env:esp32dev_ota]` hardcodes
   `--host_ip=192.168.4.61` (an older Mac dev box). Set it to **this machine's** LAN IP.
   Otherwise espota fails with "No response from the ESP".
3. **Windows only:** add a Windows Firewall inbound-allow rule for PlatformIO's
   `penv\Scripts\python.exe`, or OTA times out.
4. **GitHub push auth:** the old PC used a repo-local `core.sshCommand` with a deploy key
   that did not come with the clone. On this machine, use your own GitHub credentials.
5. **PlatformIO:** if `pio` isn't on PATH, look for it at
   `~/.platformio/penv/Scripts/pio(.exe)`. The USB-serial chips are CH340K, so the CH340
   driver is required, and COM port numbers change when boards are replugged.

## Commands

```
pio run -e esp32dev                                    # build control-point firmware
pio run -e esp32dev -t upload --upload-port <COMx|/dev/ttyUSBx>
pio run -e esp32dev_ota -t upload --upload-port airsoft-controlpoint-<id>.local
scp server/app.py airsoft@airsoft-pi.local:~/airsoft-dashboard/app.py
ssh airsoft@airsoft-pi.local 'sudo systemctl restart airsoft-dashboard'
```

- **OTA can drop mid-transfer** on weak WiFi or power. Just retry.
- **Target nodes by their `.local` names.** Their DHCP IPs move.
- **The server has no git.** Deploy `app.py` with scp, as above.

## Hardware gotchas (most expensive first)

- **WiFi `reason 201` (NO_AP_FOUND):** the ESP32-WROOM-**32U** has no PCB antenna, so first
  check that the IPEX antenna is attached. A 5 GHz-only SSID or a truncated SSID causes the
  same error.
- **Boot hangs right after printing `node type:`:** the USB power is too weak (old hubs), and
  the board browns out at `WiFi.mode()`. Use a direct or powered port, or the 5 V supply.
- **All WS2812s, including the status pixel on GPIO 2, go through FastLED.** Don't use
  `neopixelWrite`; it breaks FastLED's pin binding.
- **"GPIO 227 invalid pin" at boot is harmless.** It comes from TFT_eSPI.
- **Server PC (HP All-in-One):** it won't POST (7 blinks) unless the display backlight cable
  stays connected. Keep its hostname `airsoft-pi` so nodes find the broker at
  `airsoft-pi.local` with no firmware change. On Mosquitto 2.x, the broker needs
  `listener 1883` and `allow_anonymous true`.

## Stale docs and conflicting facts (verify before relying on them)

- **Displays:** CLAUDE.md describes TM1637 7-segment displays and a 60-LED/m 2 m strip.
  The real build uses an **ST7789 LCD**, an optional SSD1306 OLED, and **300 LEDs**. The
  `PIN_DISP_*` defines in config.h are legacy.
- **Server:** CLAUDE.md says Raspberry Pi Zero 2 W, and server/README.md uses the old Pi IP
  `192.168.88.129`. The server was migrated to an HP All-in-One running Ubuntu Server, at
  `airsoft-pi.local`.
- **Network addressing:** the older docs say the dev LAN is `192.168.88.x`. A 2026-09-12
  commit says Ground Control now hands out **`192.168.4.x`**, with the broker at `.58`.
  Use mDNS names, and confirm actual addresses with the user.
- **Field WiFi on deployed boxes:** the deployed boxes may still run a build with a
  placeholder Field preset. Ask the user whether they've been reflashed with the real field
  credentials. If not, that's the top pending task: fill in the creds, bump the version, and
  flash all three. In the meantime, the boxes reach the field by joining a spare router that
  broadcasts "Ground Control".
- **Rush rules:** the server implements defuse as **pause** (the attacker's arm time resumes)
  and has a referee-set sudden-death defuse hold (`RUSH_DEFUSE_MAX` = 5 s). Treat both as
  current behavior unless the user says otherwise.

## Backlog (summary; details in HANDOFF.md §7)

1. Reflash the boxes with the real Field WiFi preset (see above).
2. Illuminated arcade-button lamps (Adafruit 1190) on GPIO 32/33, driven through MOSFETs.
3. Flag and referee node types (`game_flag.cpp`, `game_referee.cpp`).
4. Capture-All-Flags and Classic CTF modes.
5. MQTT `set_wifi` command plus a dashboard control, for re-pointing sealed boxes.
6. Generate voice-pack audio clips and copy them to the server.
7. SQLite match history.
