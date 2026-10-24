# AGENTS.md — start here

The single reference for an AI coding agent working on this project, on any machine. It
covers the goals, architecture, conventions, current state, rules, machine setup, hardware
gotchas and backlog. It replaces the old HANDOFF.md and the old contents of CLAUDE.md
(CLAUDE.md now just imports this file).

_Last updated: 2026-10-17. Handed off from a Windows 11 dev PC to a Linux laptop._

Other docs, as needed: [FIELD_DEPLOY.md](FIELD_DEPLOY.md) (hands-on build, flash, and deploy
runbook), [WIRING.md](WIRING.md), [PROJECT_SPEC.md](PROJECT_SPEC.md), and
[server/README.md](server/README.md). Some facts in those are out of date (§13).

---

## 1. What this is

A WiFi-connected network of game control points for indoor airsoft. Players hold a
team-colored button to capture a point. LED strips and an LCD show who owns it, and each
node reports to a central server over MQTT. The server runs a live web dashboard (with audio
announcements) and the game modes.

**Long-term goals:** about 12 networked nodes that:
1. Track control point ownership and elapsed hold time per team.
2. Show ownership on LED strips and displays.
3. Report state to the central server over MQTT.
4. Show live game state on a web dashboard that any phone or laptop on the field WiFi can
   open.
5. Play audio announcements when the game state changes.
6. Support several game modes: King of the Hill, Capture All Flags, Classic CTF (and Rush,
   which was added later).

**Planned node types** (all share one firmware base):

| Type | Planned units | Inputs and outputs | Status |
|---|---|---|---|
| Control point | 5 | Red and blue buttons, LCD scoreboard, LED strip. Tracks hold time per team. | **3 built and deployed** |
| Flag | 4–5 | Red and blue buttons, LED strip. Ownership only, no timers. | Not built |
| Referee button | 2 | Red and blue buttons, optional reset/undo button, short LED strip. Used at spawn points for Classic CTF scoring. | Not built |

Every node also has a power switch, a reset button, and USB-C or barrel-jack power.

---

## 2. Where it stands now

- **Firmware** (`src/`, PlatformIO, Arduino-ESP32): `FIRMWARE_VERSION` **45** in [src/config.h](src/config.h).
- **Server** ([server/app.py](server/app.py), a single Flask + paho-mqtt + SSE file): `DASH_VERSION` **16**.
- **Deployed:** 3 control points in sealed enclosures, each powered by a 5 V / 5 A supply
  with no USB access, so they're updated over WiFi (OTA) only:
  - `alpha` = Pink Hallway
  - `bravo` = Kill House
  - `charlie` = Dark Room
  - Hostnames are `airsoft-controlpoint-<id>.local`.
  - All three run the real Field WiFi credentials (user confirmed on 2026-10-17).
- **Game modes that work:**
  - **Domination (score-based King of the Hill, since dash v12):** each held box earns its
    team points, with a "rubber band" catch-up so a team that falls far behind can come
    back. Scoring runs entirely in `server/app.py` (see "Domination scoring" in §7).
  - **Rush:** sequential bomb arming. The boxes act only as ownership sensors that don't
    know the game mode; the Rush state machine runs entirely in `server/app.py`.
- **Other features that work end to end:**
  - ST7789 LCD scoreboard, plus an optional OLED.
  - A 300-LED strip per node.
  - The live dashboard (dash v14 and later):
    - `http://airsoft-pi.local:8080/` is the read-only **player view**: scores, clock and box
      ownership.
    - `/ref` is the **referee page**: start/stop, reset, mode and catch-up. It needs a single
      6-digit PIN.
  - Browser audio announcements, with a voice-pack system that falls back to TTS.
- **Not built yet:** flag and referee node types, Capture-All-Flags and CTF modes,
  arcade-button lamps, and SQLite match history. See the backlog (§14).

---

## 3. Rules the user expects you to follow

- **Bump the version on every change:** add 1 to `FIRMWARE_VERSION` for firmware edits and to
  `DASH_VERSION` for dashboard edits. These are plain integers, not semver. Both are shown
  on-device or on-page, so the user can confirm a flash or deploy landed.
- **Commit once per major section of work**, not per tiny edit, and push to `origin main`
  (`ssh://git@github.com/imikejackson/AirsoftGameControl`). End each commit message with your
  `Co-Authored-By:` trailer.
- **Never commit secrets.** `src/secrets.h` (WiFi and OTA passwords) and `field-guide.svg`
  (contains the WiFi password) are gitignored on purpose. Get the real values from the user,
  never from git history.
- **Don't full-erase a node's flash.** It wipes `node_id` in NVS, and the box comes back as
  `alpha` and publishes under the wrong MQTT topic. A brand-new bench board also starts as
  `alpha`, so give it its own ID with the serial `nodeid <id>` command before it reaches the
  broker. To fix WiFi, use the serial `wifi`, `preset`, or `nodeid` commands instead of erasing.
- Follow the architecture principles (§4) and code conventions (§6).

---

## 4. Architecture principles

- **Local state is authoritative.** Each ESP32 keeps its own game state. WiFi and MQTT
  *report* state; they don't *run* the game. Buttons, displays and LEDs must keep working if
  the network drops.
  - One exception: in Connected mode, the dashboard owns the **game clock**. It runs the
    countdown and ends the round at 0, and nodes treat the retained `airsoft/game/state`
    topic as the source of truth for run state and time remaining.
- **Common firmware base across node types.** About 80% of the code is shared (WiFi, MQTT,
  OTA, reconnection, heartbeats). Each node type adds its own game logic on top.
- **Everything goes over MQTT.** Nodes and the server talk only through MQTT pub/sub. The
  dashboard subscribes to MQTT and never connects to nodes directly.
- **Resilient networking:**
  - Non-blocking reconnection with backoff.
  - QoS 1, with retained messages for current state.
  - MQTT Last Will and Testament to detect offline nodes.
  - A heartbeat every 12 s.
- **OTA from day one.** Nodes live in sealed enclosures, so USB access is impractical.

---

## 5. MQTT topics

```
airsoft/<node_type>/<node_id>/state        # Node publishes state updates (retained)
airsoft/<node_type>/<node_id>/command      # Node subscribes for commands (reset, etc.)
airsoft/<node_type>/<node_id>/status       # LWT online/offline (retained)
airsoft/<node_type>/<node_id>/heartbeat    # Periodic alive signal
airsoft/game/state                         # Game mode, run state, time remaining, Domination team scores (retained; written by the dashboard)
airsoft/game/command                       # Server commands to all nodes (reset_all, etc.)
```

- **Node types:** `controlpoint`, `flag`, `referee`.
- **Node IDs:**
  - Control points use phonetic names (alpha, bravo, charlie, delta, echo).
  - Flags and referee buttons are numbered.
- **Broker:** `airsoft-pi.local:1883` by default. Change it at runtime over serial with
  `mqtt <host> <port>`.

---

## 6. Code conventions

- **Timing:** track all time in milliseconds with `millis()`. Never use `delay()` in main
  loops.
- **Nothing blocks:** the main loop must always be free to handle buttons and the network.
- **MQTT publishes** must not block. Messages aren't queued while the node is
  disconnected. On reconnect, it publishes "online" and a fresh retained state snapshot, so
  the server catches up. (The original spec asked for a queue; the snapshot is how it was
  built.)
- **Buttons:**
  - Use `INPUT_PULLUP` on button GPIOs and wire each button to GND, with no external
    pull-up resistors.
  - Debounce every button, at least 50 ms (`BUTTON_DEBOUNCE_MS`).
- **Settings storage:** keep the node ID and WiFi credentials in NVS (the Preferences
  library, namespace `airsoft`), not hardcoded. `secrets.h` only provides first-boot
  defaults.
- **Logging:** log significant events to Serial at 115200 baud.
- **Tunables:** timing values, pins and LED settings live in [src/config.h](src/config.h).
  Change them there.

---

## 7. Game behavior (control point firmware)

**Capture and timers:**
- **Capture is instant (since v44):** a single press captures the point as soon as it
  clears the 50 ms debounce (`CAPTURE_HOLD_MS` = 0). The original spec asked for a 2–3 s
  hold to stop griefing. It was cut to 0.5 s and then to zero because players found any hold
  too slow. Don't add a hold back unless the user asks.
  - If `CAPTURE_HOLD_MS` is ever raised again, the hold returns along with its progress bar
    and the 200 ms grace window (`CAPTURE_GRACE_MS`), which pauses rather than restarts
    the countdown when a button contact flickers.
- **Pressing your own team's button** while you already hold the point does nothing, so
  there are no accidental resets.
- **Per-box timers are cumulative:** when a team takes a point, the other team's time stays.
  The box LCD and the dashboard tiles show each team's total time on that box. Since dash
  v12 these times are only for information: Domination's winner is decided by score.

**Reset:**
- Resetting is always explicit and is the only way to zero the timers and make the point
  neutral. It can come from the box's reset button or from an MQTT command sent by the
  dashboard.
- **Tap** the reset button to reset.
- **Hold** it for 1.5 s (`RESET_HOLD_MS`) to open the local game menu, which starts a
  standalone game without the server.

**Boot and config menus:**
1. The LCD first shows a **WiFi picker** for the presets in `secrets.h`.
2. Next is a **mode picker**: Connected (driven by the server) or a local standalone game.
3. Each menu picks a default after 15 s with no input: the last-used network, then
   Connected. So a box that loses power in the field reconnects on its own.
4. **Hold both team buttons for 10 s** (`COMBO_HOLD_MS`) to reopen these menus without
   rebooting. This works on sealed boxes.

**Domination scoring (server-side, dash v12):**
- Each box a team holds earns it 1 point every 5 s (`DOM_TICK_S`). The highest score when
  time runs out wins. Offline boxes, and boxes silent for 30 s, don't score.
- **Rubber band ("Catch-up", set from the dashboard: Off, Low, Medium, High):**
  - Leads of up to 20 points are left alone (`DOM_DEADZONE_PTS`), so a lead earned by
    playing well isn't worn away by even play.
  - Beyond 20 points, the leader's points come slower and the trailer's come faster. The
    effect reaches full strength over the next 30 points (`DOM_RAMP_PTS`).
  - At full strength, the trailing team's per-box rate is 1.5×, 2× or 3× the leader's
    (`DOM_CATCHUP`: Low, Medium or High). Medium is the default. The change is split evenly
    between the two teams.
  - Holding more boxes always matters. At Medium, a trailing team holding 1 box only keeps
    pace with a leader holding 2.
- Start and Reset All zero the scores. The catch-up level can be changed mid-round.
- The team scores are also published as `score_red` and `score_blue` in
  `airsoft/game/state`, so the box firmware could show them in the future. It doesn't yet.

**Player view and referee PIN (dash v14):**
- Anyone on the field WiFi can open `/`. It shows no controls.
- `/ref` asks for the PIN once per browser. The login lasts until the dashboard restarts,
  which logs every referee out.
- `/api/command` refuses everything (HTTP 403) without a referee login. **This server check
  is what protects the game; hidden buttons alone would not.**
- **Where the PIN comes from:** `$AIRSOFT_REF_PIN`, otherwise `server/ref_pin.txt`
  (gitignored; on the server it's `~/airsoft-dashboard/ref_pin.txt`). If neither exists, a
  PIN is generated, saved to that file, and printed once in the log.
  - **The user chose a fixed PIN.** It's kept in `server/ref_pin.txt` on the dev laptop and
    copied to the server with the deploy commands in §10. **The GitHub repo is public, so
    never put the PIN in code, docs or commits.** Ask the user for it if it's lost.
  - To read it on the server: `cat ~/airsoft-dashboard/ref_pin.txt`
  - To change it: write a new 6-digit PIN to that file, then restart the service.
- **Lockout:** after 5 wrong PINs, that device is locked out for 60 s.
- The site is plain HTTP, so someone capturing WiFi traffic could read the PIN. That was
  accepted as good enough for a game.

**Connection monitoring (dash v16):** the server tracks whether each box stays connected.
Added because the user suspects Dark Room (charlie) drops off. It records:
- **offline:** the broker delivered the box's last-will message.
- **silent:** no message from the box for 30 s (`CONN_SILENT_S`); heartbeats come every
  12 s.
- **back:** the box was heard from again after offline or silent, with the downtime.
- **reboot:** the box's heartbeat uptime went backwards.
- **weak / signal ok:** the signal dropped below -75 dBm, or recovered above -70. The gap
  between the two stops a borderline box from flooding the log.

Retained messages, which the broker replays when the dashboard starts, never count as proof
that a box is alive.

Where to see it:
- Each referee tile shows this round's drops, reboots and offline time, plus a live "DOWN"
  while a box is out. Start resets the counters.
- `/ref` has a **Connection log** panel, fed by `/api/connlog` (referee only).
- Every event is appended to `server/logs/connections.log` (gitignored; on the server it's
  `~/airsoft-dashboard/logs/`), so a whole game day can be reviewed later.

**WiFi signal on referee tiles (dash v15):**
- Each box tile on `/ref` shows its current signal from the 12 s heartbeat, colored green
  at -67 dBm or better, yellow from -67 to -75, and red below -75.
- Once the signal has dipped, the tile also shows the **worst** reading since the round
  started. The server tracks this and resets it on Start.
- Players don't see it.
- **Field reference (2026-10-23):** all three boxes read -47 to -56 dBm on the field WiFi
  (`10.0.0.x`, server at `10.0.0.84`).
- **Antenna extension test (2026-10-24):** the user's Gigabyte extension cable, with a
  hand-made wire joint, cost about 0–2 dB compared with the antenna directly on the board.
  The joint must be secured, because readings shifted when it was handled. The thin coax on
  these small antenna connectors loses about 3–4 dB per meter, so mount the antenna on the
  box wall with an RP-SMA bulkhead rather than running long cable.

**Box screen simulator (dash v13):** the dashboard's "Box screens" control (or a
`?sim=time` / `?sim=score` link) draws an approximate copy of each box's 320×240 LCD on its
tile. It mirrors `lcdShowGame()` in [src/lcd.cpp](src/lcd.cpp). Use it to try out screen
designs in the browser before porting them to firmware. If you change the LCD layout, keep
`drawBoxScreen()` in `server/app.py` in step with it. Boxes don't report their firmware
version over MQTT, so the simulated screen shows `v?`.

**Sleep:** after 10 minutes with no game running and no button presses, the box blanks its
displays and runs a rainbow LED chase. Any button press, or a game starting, wakes it.

**Serial commands:** `wifi <ssid> <pass>`, `presets`, `preset <n>`, `nodeid <id>`,
`netstatus`, `mqtt <host> <port>`, `mqttstatus`, `reset`, `score`.

**LED behavior (since v25):**

| State | Strip shows |
|---|---|
| Boot | Self-test sweep: red, then green, then blue |
| Neutral, game stopped | White, breathing |
| Neutral, game running | Green |
| Being captured | Progress fill in the capturing team's color |
| Held | Comet-train chase in the owner's color |
| Paused or game over | Static, dim team color |
| Asleep | Rainbow chase |

`setMaxPowerInVoltsAndMilliamps(5, 4500)` caps power and dims the strip automatically to
protect the 5 V / 5 A supply. The tunables (`CHASE_*`, `NUM_LEDS`, `LED_*`) are in config.h.

---

## 8. Software stack and file layout

**Firmware libraries** (Arduino on ESP32, through PlatformIO):
- **MQTT and JSON:** `PubSubClient`, `ArduinoJson`
- **LEDs:** `FastLED`, for the strip and the status pixel
- **LCD:** `TFT_eSPI` (ST7789)
- **OLED:** `Adafruit GFX` and `Adafruit SSD1306`
- **Built into the ESP32 core:** `WiFi`, `Preferences` and `ArduinoOTA`

**Server** (`airsoft-pi.local`):
- **Mosquitto** is the MQTT broker.
- **`app.py`** runs Flask on port 8080 and pushes live updates to the dashboard with
  Server-Sent Events.
- **Audio** plays in the browser.
- **Match history** (SQLite) isn't built yet.

**Repository layout:**

```
src/
  main.cpp                   # setup() and loop()
  config.h                   # version, pins, timing, tunables, node type selection
  types.h                    # shared types
  secrets.example.h          # template for the gitignored secrets.h
  network.cpp/.h             # WiFi, presets, boot pickers, serial config commands
  mqtt.cpp/.h                # MQTT client, LWT, heartbeats, state snapshot on reconnect
  ota.cpp/.h                 # ArduinoOTA
  buttons.cpp/.h             # debouncing and press/hold detection
  game_controlpoint.cpp/.h   # control point game logic
  lcd.cpp/.h                 # ST7789 scoreboard (TFT_eSPI)
  oled.cpp/.h                # optional SSD1306
  leds.cpp/.h                # WS2812B strip (FastLED)
  statusled.cpp/.h           # onboard status pixel (FastLED)
server/
  app.py                     # dashboard, game clock, Rush logic
  deploy.sh                  # server install script
  README.md
platformio.ini               # one environment per node type, plus OTA
```

`game_flag.cpp` and `game_referee.cpp` will be added when those node types are built.

---

## 9. First-time setup on a new machine

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

## 10. Build, flash, OTA, and server deploy

```
pio run -e esp32dev                                    # build control-point firmware
pio run -e esp32dev -t upload --upload-port <COMx|/dev/ttyUSBx>        # USB (bench)
pio run -e esp32dev_ota -t upload --upload-port airsoft-controlpoint-<id>.local   # OTA (deployed)
pio device monitor                                     # serial monitor, 115200 baud
scp server/app.py airsoft@airsoft-pi.local:~/airsoft-dashboard/app.py
scp server/ref_pin.txt airsoft@airsoft-pi.local:~/airsoft-dashboard/ref_pin.txt   # referee PIN (gitignored)
ssh airsoft@airsoft-pi.local 'sudo systemctl restart airsoft-dashboard'
```

The PlatformIO toolbar in VS Code does the same jobs: the checkmark builds, the arrow
uploads over USB, and the plug opens the serial monitor.

- **OTA can drop mid-transfer** on weak WiFi or power, stopping at a random percentage. Just
  retry; it usually completes within a few tries. A retry loop that stops on "SUCCESS" works.
- **OTA device side:** ArduinoOTA listens on **port 3232** and advertises
  `<hostname>.local`. If `OTA_PASSWORD` is set in secrets.h, add
  `--upload-flags --auth=<password>` to the upload command.
- **OTA only works on a node that is already online.** A bricked or offline node needs USB
  recovery: open the box, plug in a cable, and flash over USB.
- **Target nodes by their `.local` names.** Their DHCP IPs move.
- **The server has no git.** Deploy `app.py` with scp, as above.

**Local test server (no Docker, no sudo):** on 2026-10-17 the user said the
`airsoft-pi.local` broker is no longer running, so bench testing used a broker and dashboard
running on the dev laptop. They run from a conda environment under Miniforge, which is
installed at `/opt/local/anaconda3`:

```
mamba create -n airsoft -c conda-forge python=3.12 mosquitto flask paho-mqtt
# mosquitto.conf: listener 1883 0.0.0.0 / allow_anonymous true
/opt/local/anaconda3/envs/airsoft/sbin/mosquitto -c mosquitto.conf
cd server && /opt/local/anaconda3/envs/airsoft/bin/python app.py   # dashboard on :8080
```

- `app.py` already connects to the broker on `localhost`, so it needs no changes.
- Point a node at the laptop over serial with `mqtt <laptop-ip> 1883`.
- The laptop's IP comes from DHCP and can change, so recheck it if the node can't reach
  MQTT.

**PlatformIO environments ([platformio.ini](platformio.ini)):**
- They all share an `[env]` base with the common libraries and build flags.
- `esp32dev`, `controlpoint`, `flag`, and `referee` each build one node type, selected with
  `-D NODE_TYPE_IS_*`. `esp32dev` is the same as `controlpoint`.
- `esp32dev_ota` builds the same control-point firmware but uploads it over WiFi with espota.
- TFT_eSPI is configured entirely through `build_flags` (ST7789 driver, pins, fonts). Don't
  add a `User_Setup.h`.

---

## 11. Network map

| Thing | Hostname (mDNS) | Notes |
|---|---|---|
| Control point alpha | `airsoft-controlpoint-alpha.local` | DHCP IP changes, so use the hostname |
| Control point bravo | `airsoft-controlpoint-bravo.local` | Same |
| Control point charlie | `airsoft-controlpoint-charlie.local` | Same |
| Bench/dev board gamma (not deployed) | `airsoft-controlpoint-gamma.local` | USB on the Linux dev laptop; node ID set 2026-10-17 |
| Central server / broker | `airsoft-pi.local` | Mosquitto on :1883, dashboard on :8080 |

- **Node IPs move:** they have been .36/.37/.39 and later .49/.50/.52. Always use the `.local`
  hostnames. DHCP reservations by MAC address would be an optional fix.

---

## 12. Hardware

**Gotchas, most expensive first:**
- **FastLED is pinned to 3.10.3 in platformio.ini, and must stay pinned.** The library used
  to be `^3.6`, so each machine built with whatever version it first downloaded.
  - v44, built on the Linux laptop, pulled FastLED **3.10.8** (released 2026-10-18).
  - With 3.10.8, the strips showed a frozen **full white fading to yellow**: the strip
    misread the data timing, so every bit read as 1.
  - That load is far beyond the 5 V / 5 A supply. It made Dark Room (charlie) brown out
    and reboot about every minute.
  - **3.10.5 doesn't fit**: the program is 1.35 MB against a 1.31 MB limit. The app
    partition can only be enlarged over USB.
  - **3.10.3** builds at about 940 KB. That matches the ~930 KB images the old Windows PC
    produced, and it was confirmed fixed in the field on 2026-10-24 (v45).
  - Only upgrade FastLED after testing a strip on the bench.
- **WiFi `reason 201` (NO_AP_FOUND):** the ESP32-WROOM-**32U** has no PCB antenna, so first
  check that the IPEX antenna is attached. A 5 GHz-only SSID or a truncated SSID causes the
  same error.
- **Boot hangs right after printing `node type:`:** the USB power is too weak (old hubs), and
  the board browns out at `WiFi.mode()`. Use a direct or powered port, or the 5 V supply.
  This differs from the antenna fault: with a missing antenna, WiFi starts but finds no
  access point.
- **All WS2812s, including the status pixel on GPIO 2, go through FastLED.** Don't use
  `neopixelWrite`. Mixing it with FastLED's RMT driver stops FastLED from binding the strip
  pin. (The status-LED comment in config.h still mentions `neopixelWrite`; it's stale.)
- **"GPIO 227 invalid pin" at boot is harmless.** It comes from TFT_eSPI's LCD setup, not
  the LEDs.

**Pin assignments (control point, as built):**

| Function | GPIO | Defined in |
|---|---|---|
| Red button | 25 | config.h `PIN_BTN_RED` |
| Blue button | 26 | config.h `PIN_BTN_BLUE` |
| Reset button (optional) | 27 | config.h `PIN_BTN_RESET` |
| LED strip data | 5 | config.h `PIN_LED_DATA` |
| Onboard status pixel | 2 | config.h `PIN_STATUS_RGB` |
| ST7789 LCD: MOSI / SCLK / CS / DC / RST | 23 / 18 / 4 / 17 / 16 | platformio.ini `build_flags` |
| SSD1306 OLED: SDA / SCL (I2C 0x3C) | 21 / 22 | config.h `PIN_OLED_*` |
| Arcade-button lamps (planned) | 32 / 33 | not yet |

- Avoid GPIO 6–11 (wired to the flash chip).
- Be careful with the strapping pins 0, 2, 12 and 15. GPIO 2 is safe for the status pixel
  because it's only driven after boot.
- The `PIN_DISP_*` defines in config.h are left over from the original TM1637 plan. They
  share pins with the LCD and OLED and aren't used.

**Per control-point node:**
- **ESP32:** Lonely Binary ESP32-WROOM-32U with a CH340K USB chip and USB-C. It needs its
  external IPEX antenna.
- **LED strip:** WS2812B, IP65, **300 LEDs**, data on **GPIO 5**. It runs off the external
  5 V supply and shares ground with the ESP32.
  - Put a 1000 µF capacitor across the strip's power input.
  - Put a 330–470 Ω resistor in series with the data line.
  - At full white, each LED draws about 60 mA. The 5 A supply only covers about 80 LEDs at
    full white, so the FastLED power cap is what keeps the 300-LED strip safe.
  - On long runs, inject 5 V at both ends to avoid dimming at the far end.
- **Displays:** **ST7789 2" LCD** (SPI) as the scoreboard. An **SSD1306 OLED** (I2C) is
  optional; the firmware checks for it at boot.
- **Buttons:** simple 2-terminal buttons, wired active-low with `INPUT_PULLUP`.
- **Assembly:** JST-SM connectors (so parts can be swapped out) in a weather-resistant ABS
  enclosure.

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

**Central server:**
- **Hardware:** an HP All-in-One 22-dd0123w (Pentium Silver J5040, 4 GB RAM, SSD) running
  **Ubuntu Server 26.04 LTS**, headless over SSH. It replaced the original Raspberry Pi Zero
  2 W.
  - Its screen is broken and removed, but it **won't POST (7 blinks) unless the display
    backlight cable stays connected**, so leave the dead panel attached.
  - Its HDMI port is an output, so an external monitor works.
- **Hostname stays `airsoft-pi`**, so nodes find the broker at `airsoft-pi.local` with no
  firmware change. `avahi-daemon` provides the `.local` name.
- **Mosquitto 2.x** needs `listener 1883` and `allow_anonymous true`.
- **`deploy.sh`** installs `mosquitto python3-flask python3-paho-mqtt` with apt, sets up the
  systemd service, and creates the sound-pack folders.
- **Ubuntu 26.04 enforces PEP 668,** so install Python packages with apt or in a venv, never
  with system `pip`.

---

## 13. Stale docs and conflicting facts (verify before relying on them)

- **Display hardware:** PROJECT_SPEC.md and other older docs may describe TM1637 7-segment
  displays and a 60-LED/m 2 m strip. The real build uses an **ST7789 LCD**, an optional
  SSD1306 OLED, and **300 LEDs** (§12).
- **Server:** older docs say Raspberry Pi Zero 2 W, and server/README.md uses the old Pi IP
  `192.168.88.129`. The real server is the HP box at `airsoft-pi.local` (§12).
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

## 14. Backlog (agreed but not built)

1. **Illuminated arcade-button lamps** (Adafruit 1190):
   - Add `PIN_LAMP_RED`/`PIN_LAMP_BLUE` on GPIO 32/33.
   - Drive each lamp through a low-side MOSFET.
   - In firmware, light each button in its team color and pulse it on capture.
   - The lamps are dim on 5 V; add a 12 V lamp supply for full brightness.
2. **Flag and referee node types** (`game_flag.cpp`, `game_referee.cpp`), layered on the
   shared base (§1, §4).
3. **Capture-All-Flags and Classic CTF modes.**
4. **MQTT `set_wifi` command plus a dashboard control,** for re-pointing sealed boxes. The
   serial `wifi <ssid> <pass>` command already exists in network.cpp, but it needs a USB
   cable, which sealed boxes don't have.
5. **Field WiFi hardware.** The Pi's onboard antenna was too weak to act as the access
   point. The decision is a **dedicated router/AP with external antennas**, with the server
   connected by Ethernet. Running OPNsense on the HP box was considered and rejected: it is
   a router/firewall OS with poor WiFi access-point support, and it doesn't host the app
   stack well.
6. **Field-speaker audio (planned dash v15):** play the announcements from the server's own
   headphone jack into the field PA. The user confirmed the NUC has a headphone port. The
   clips and their exact words are listed in [server/voice_clips.csv](server/voice_clips.csv);
   generate them (Piper is the plan) and scp them to the server.
7. **SQLite match history.**
8. **WIRING.md:** document the USB-C power pigtail and the arcade-button pinout.
