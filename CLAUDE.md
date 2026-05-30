# Airsoft Control Point System

A WiFi-connected network of game control points for indoor airsoft. Players push team-colored buttons to capture points; timers and LED strips show ownership; a central server publishes live status to a web dashboard with audio announcements.

## Project Goals

Build a scalable system of ~12 networked nodes that:
1. Track control point ownership and elapsed hold times per team
2. Visualize ownership via LED strips and digital displays
3. Report state to a central server over MQTT
4. Display live game state on a web dashboard accessible from any device on the field WiFi
5. Trigger pre-recorded audio announcements over field speakers when state changes
6. Support multiple game modes (King of the Hill, Capture All Flags, Classic CTF)

## Node Types

The system supports three node types, all sharing a common firmware base:

- **Control Point** (5 units) — Two buttons (red/blue), two 4-digit displays (red/blue), LED strip. Tracks elapsed hold time per team.
- **Flag Node** (4-5 units) — Two buttons (red/blue), LED strip. Tracks ownership only, no timers.
- **Referee Button** (2 units) — Two buttons (red/blue) plus optional reset/undo button, short LED strip. Used at spawn points for classic CTF scoring.

Each node also has: power switch, reset button, USB-C or barrel-jack power input.

## Hardware Stack

**Per Node:**
- ESP32 (Lonely Binary ESP32-WROOM-32U with external IPEX antenna, CH340K USB chip)
- WS2812B LED strip (60 LEDs/m, IP65, length varies by node type — typically 2m)
- 5V 5A power supply (barrel jack) — powers LED strip and ESP32
- 1000µF capacitor across LED strip power input
- 330-470Ω resistor inline on LED data line
- JST-SM connectors for serviceability
- Weather-resistant ABS enclosure

**Control Point Additional:**
- 2x TM1637 4-digit 7-segment displays (one red, one blue, 0.56" digit height)
- 2x large arcade buttons (red and blue, illuminated 60mm style)

**Flag/Referee Additional:**
- 2x large arcade buttons (red and blue)

**Central Server:**
- Raspberry Pi Zero 2 W (or similar)
- USB audio adapter + powered PA speaker for announcements
- Optionally configured as WiFi AP for field deployment

## Software Stack

**Firmware:** Arduino framework on ESP32 via PlatformIO
- `PubSubClient` for MQTT
- `FastLED` for LED strip control
- `TM1637` library for 7-segment displays
- `ArduinoJson` for MQTT payload parsing
- `ArduinoOTA` for over-the-air updates

**Server:** Raspberry Pi running:
- Mosquitto MQTT broker
- Node.js or Python web server (Flask/Express) for dashboard
- WebSocket or Server-Sent Events for live dashboard updates
- Audio playback service (mpg123, pygame.mixer, or similar)
- SQLite for match history logging

**Dashboard:** Browser-based, accessible at `http://airsoft-pi.local:8080`. Live-updating tiles per node, score displays, game mode selector, manual reset controls.

## Architectural Principles

**Local state is authoritative.** Each ESP32 maintains its game state independently. WiFi/MQTT is for *reporting* state, not *running* the game. Buttons, displays, and LED strips must continue working if the network drops.

**Common firmware base across node types.** ~80% of code is shared (WiFi, MQTT, OTA, reconnection, heartbeats). Each node type layers its game logic on top.

**MQTT-first architecture.** All inter-node and node-to-server communication is via MQTT pub/sub. The dashboard subscribes to MQTT topics; it has no direct connection to nodes.

**Resilient networking.** Aggressive non-blocking reconnection, QoS 1 with retained messages for current state, MQTT Last Will and Testament for offline detection, heartbeats every 10-15 seconds.

**OTA from day one.** Once nodes are deployed in enclosures, USB access is impractical. Build OTA update support into the base firmware.

## MQTT Topic Schema

```
airsoft/<node_type>/<node_id>/state        # Node publishes state updates (retained)
airsoft/<node_type>/<node_id>/command      # Node subscribes for commands (reset, etc.)
airsoft/<node_type>/<node_id>/status       # LWT online/offline (retained)
airsoft/<node_type>/<node_id>/heartbeat    # Periodic alive signal
airsoft/game/state                         # Current game mode, start/stop, score
airsoft/game/command                       # Server commands to all nodes (reset_all, etc.)
```

Node types: `controlpoint`, `flag`, `referee`
Node IDs: use phonetic names (alpha, bravo, charlie, delta, echo) for control points; numbered for flags and referee buttons.

## Game Logic Conventions

**Cumulative timer model (King of the Hill):** When a team captures a previously-held point, the other team's accumulated time persists. The dashboard shows total cumulative time per team per point.

**Capture debouncing:** Buttons must be held 2-3 seconds to register a capture. Prevents accidental griefing.

**Own-team button ignored:** Pressing your own team's button while you already hold the point does nothing — no accidental resets.

**Reset is explicit:** The reset button (separate from the team buttons) zeros all timers and restores neutral state. Issued either physically at the node or via MQTT command from the dashboard.

## Code Conventions

- All time tracking in milliseconds via `millis()`, never `delay()` in main loops
- Non-blocking everything — main loop must always be free to handle buttons and network
- Use `INPUT_PULLUP` on button GPIOs, wire buttons to GND (no external pull-up resistors)
- Debounce all buttons (50ms minimum)
- Store node ID and WiFi credentials in NVS (preferences library), not hardcoded
- Log significant events to Serial at 115200 baud for debugging
- All MQTT publishes should be non-blocking; queue if disconnected, send when reconnected

## File Structure

```
src/
  main.cpp              # Entry point, setup() and loop()
  config.h              # Pin assignments, constants, node type selection
  network.cpp/.h        # WiFi + MQTT + OTA
  display.cpp/.h        # TM1637 display abstraction (control points only)
  leds.cpp/.h           # FastLED strip control and animations
  buttons.cpp/.h        # Button debouncing and event detection
  game_controlpoint.cpp # Control point game logic
  game_flag.cpp         # Flag node game logic
  game_referee.cpp      # Referee button logic
platformio.ini          # Multiple environments per node type
```

## Build Environments

`platformio.ini` defines separate environments for each node type, sharing common library dependencies and build flags. Compile flags select which game logic module is included.

## Common Commands

- Build: PlatformIO Build button (checkmark icon in bottom toolbar)
- Upload via USB: PlatformIO Upload button (arrow icon)
- Upload via OTA: `pio run -t upload --upload-port <node-ip>.local`
- Serial Monitor: PlatformIO Serial Monitor button (plug icon), 115200 baud

## Pin Assignments (Control Point Reference)

| Function | GPIO |
|----------|------|
| Red button | 25 |
| Blue button | 26 |
| Reset button | 27 |
| Red display CLK | 18 |
| Red display DIO | 19 |
| Blue display CLK | 22 |
| Blue display DIO | 23 |
| LED strip data | 5 |

Avoid GPIO 6-11 (flash). Be cautious with strapping pins 0, 2, 12, 15.

## Status / Current Phase

Initial firmware development. Dev environment confirmed working: VS Code + PlatformIO + CH340K driver + hello world running on ESP32. Hardware ordered but not all received. Next step: implement WiFi + MQTT base before display/button code, since networking is the highest-risk component.
