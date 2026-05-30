# Airsoft Control Point System — Project Specification

This document captures the full design and rationale for the airsoft control point system. It exists as a deeper reference alongside `CLAUDE.md` (which is a concise summary read every Claude Code session). When a design decision is unclear or needs context, this document explains the *why*.

## Background and Use Case

This system is designed for an indoor airsoft field that has WiFi coverage throughout, AC power at every planned node location, and approximately 100 feet maximum distance from any node to the WiFi access point. The field has wood walls and some drywall (including one room with multiple drywall walls between it and the AP).

The system supports three game modes:

1. **King of the Hill** — Several control points around the field. Each team tries to capture and hold control points. Cumulative hold-time per team is tracked at each point.
2. **Capture All Flags** — Several flag nodes around the field. Each team tries to capture all flags simultaneously to win. No timers, just current ownership.
3. **Classic CTF** — Two teams, each defends a flag and tries to capture the other team's flag. Referees at each spawn point need to register scoring events (which often happen out of sight of the main field).

## Architecture Overview

### High-Level Design

The system is a star topology centered on a Raspberry Pi running an MQTT broker and web dashboard. All control points, flag nodes, and referee buttons are ESP32-based clients that connect via WiFi and communicate exclusively through MQTT pub/sub messaging.

```
                   ┌─────────────────────┐
                   │   Raspberry Pi      │
                   │  ┌───────────────┐  │
                   │  │ Mosquitto MQTT│  │
                   │  └───────────────┘  │
                   │  ┌───────────────┐  │
                   │  │  Web Server   │  │  ──→ Dashboard accessible
                   │  └───────────────┘  │     to any device on WiFi
                   │  ┌───────────────┐  │
                   │  │ Audio Player  │  │  ──→ Powered PA speaker
                   │  └───────────────┘  │
                   └──────────┬──────────┘
                              │ WiFi
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
       ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
       │ ESP32   │       │ ESP32   │       │ ESP32   │   ... etc
       │ Control │       │  Flag   │       │ Referee │
       │  Point  │       │  Node   │       │ Button  │
       └─────────┘       └─────────┘       └─────────┘
```

### Why MQTT?

MQTT is the right protocol for this project because:

- **Pub/sub decouples publishers from subscribers.** Nodes don't need to know about the dashboard or each other. They just publish state. Subscribers (the dashboard, audio service, logger) pick up what they care about. Adding new subscribers later requires no node firmware changes.
- **Lightweight.** ESP32s have limited memory and CPU compared to a Pi. MQTT messages are tiny binary frames. HTTP/REST would be heavier and more complex to implement reliably.
- **Built-in QoS levels.** QoS 1 guarantees delivery without the complexity of QoS 2. Critical for state-change events.
- **Retained messages.** When a new client (e.g., a player's phone opening the dashboard) connects, it immediately receives the last-known state of every topic. No "wait for the next update" lag.
- **Last Will and Testament (LWT).** Each node tells the broker "if I disconnect unexpectedly, publish this 'offline' message on my behalf." Critical for detecting failed nodes in real-time.
- **Mature library support.** PubSubClient is a well-tested Arduino library used by tens of thousands of projects.

### Why a Central Server (vs. Peer-to-Peer)?

An alternative architecture would have each ESP32 expose its state via a small HTTP server, with the dashboard polling each node. Pros: simpler to set up initially, no central server required. Cons:

- Dashboard must know every node's IP address
- Each node must handle multiple concurrent HTTP clients (memory pressure)
- No persistence — if the dashboard isn't running, no history is recorded
- Audio announcements would require yet another component polling each node
- Scoring summaries would require the dashboard to actively poll and aggregate
- Adding a new viewer means adding load to every node

The central server pattern scales better, handles more game modes cleanly, and provides a natural place for cross-node logic (winner detection, score aggregation, match history, audio cues).

## Hardware Decisions

### ESP32 vs. Arduino Classic

The Arduino Uno/Nano family doesn't have built-in WiFi. Adding a WiFi shield (ESP8266 module or similar) means two chips talking over serial, which is fragile and limits performance. The ESP32:

- Has built-in WiFi (2.4GHz) and Bluetooth
- Dual-core 240MHz processor (way more than needed, but nice for headroom)
- Plenty of GPIO pins
- 4MB+ flash and 520KB SRAM (plenty for our use case)
- Costs about the same as a Nano with WiFi shield
- Programs with the same Arduino IDE / framework, so no learning curve

Specifically, the **ESP32-WROOM-32U variant with external IPEX antenna connector** was chosen over the more common **ESP32-WROOM-32D** (PCB antenna) because the field has walls between nodes and the WiFi access point, including one location with multiple drywall walls. An external antenna provides 10-15 dB more link margin — the difference between marginal and rock-solid connectivity.

### Specific Board: Lonely Binary ESP32

The boards purchased are 3-packs from Lonely Binary on Amazon, which include:
- ESP32-WROOM-32U module
- External IPEX antenna with whip antenna
- USB-C connector (modern, not the older micro-USB)
- CH340K USB-to-serial chip (needs WCH CH341SER driver — covers CH340/CH341 family)
- Expansion bases (screw-terminal version) for clean wiring without soldering directly to module pins
- Immersion gold PCB finish for durability

15 units total were ordered (5 three-packs), planned for 12 deployed nodes plus 3 spares.

### LED Strips: WS2812B at 60 LEDs/m, IP65

**WS2812B** (sometimes branded "NeoPixel") was chosen because:
- Individually addressable — enables team-color animations and effects
- Only needs one data pin from the ESP32
- 5V operation matches the rest of the system power
- FastLED and Adafruit NeoPixel libraries are mature and well-documented

**60 LEDs per meter** is the visual sweet spot — dense enough to look like a glowing bar (not visible dots), sparse enough to keep power consumption manageable.

**IP65 waterproofing** provides a silicone overlay that protects against BB strikes (essential for airsoft) and moisture, without making the strip rigid or hard to cut to length.

Length per node:
- Control points: 2m per node (highly visible across rooms)
- Flag nodes: 2m per node (same visibility requirement)
- Referee buttons: 0.5-1m per node (just confirmation indicator)

Total LED footage: ~25-30 meters. Buy 6 × 5m reels.

### Power Architecture

Each node has both an ESP32 and an LED strip. The LED strip can pull 1-3 amps at typical brightness (single-color, moderate brightness), which is far more than the ESP32 needs.

Two valid power schemes:

**Scheme A (development):** ESP32 powered by USB-C from a small wall adapter (existing iPhone-style 5V 1A bricks work fine for ESP32 alone). LED strip powered by separate 5V 5A supply.

**Scheme B (deployment, recommended):** Single 5V 5A power supply per node, with both ESP32 (via 5V/VIN pin on expansion base) and LED strip powered from the same supply. Cleaner install, one power cord per node.

**Critical wiring requirement:** When the LED strip and ESP32 are powered from different supplies, their grounds MUST be connected. The data signal from the ESP32 to the LED strip is referenced to ground, and without a common ground reference, the data signal will be erratic or fail entirely.

**Required power components per node:**
- 5V 5A power supply with barrel jack
- 1000µF electrolytic capacitor across LED strip power input (absorbs current spikes when LEDs change state — prevents the first LED from being damaged by inrush current)
- 330-470Ω resistor inline on the LED data line, placed close to the strip (impedance matching, prevents reflections that can corrupt data)

### Displays (Control Points Only)

**TM1637 4-digit 7-segment displays**, 0.56" digit height, color-matched to teams (red and blue).

- The TM1637 driver chip handles multiplexing and serial communication
- Only 2 GPIO pins per display (CLK and DIO) — plus VCC and GND
- Mature Arduino library (`avishorp/TM1637`)
- Cheap (~$3-5 per display)
- Readable at typical airsoft engagement distances (10-20 feet)
- The center colon (`:`) can be enabled separately to show MM:SS format

Two displays per control point (one red, one blue) for 10 displays total, plus spares = 12 displays ordered.

### Buttons

Large arcade-style buttons (60mm illuminated) for the team-color buttons. Durable, satisfying to press, visible from a distance, and the standard for projects like this.

A smaller momentary tactile button for "reset game" at each node.

A SPDT toggle switch for the on/off power switch.

All wired between GPIO and ground using the ESP32's internal `INPUT_PULLUP`. No external pull-up resistors needed.

### Central Server: Raspberry Pi Zero 2 W

A Raspberry Pi Zero 2 W is recommended for the central server because:
- $15, low power, small form factor
- Runs full Linux — can host Mosquitto, web server, audio playback, and SQLite all easily
- Has WiFi and can be configured as a WiFi access point itself if needed (via `hostapd`)
- USB host for audio adapter and other peripherals
- Plenty of CPU for the modest load (estimated 5-10 MQTT messages/sec across all nodes)

A larger Pi (4 or 5) would work fine too, but Zero 2 W is sufficient and cheaper.

### Audio System

For announcements when game state changes:
- USB audio adapter ($5-10, e.g., Sabrent or UGREEN) plugged into Pi
- Powered PA speaker (30-100W range) for arena-scale volume
- Pre-recorded audio files generated via AI voice service
- Audio playback via `mpg123`, `pygame.mixer`, or similar
- Queueing and rate limiting in software to prevent overlapping announcements

## Network Reliability

Even with external antennas, plan for occasional WiFi hiccups. The firmware must be designed to survive them gracefully.

### Local State Authority

This is the most important principle of the firmware: **each node maintains its game state locally and authoritatively**. The displays, LED strip, and button responses are driven by local state variables. MQTT publishes are *reports* of state changes, not *commands* that cause state changes.

If WiFi drops:
- Buttons still work
- Timers keep counting
- LED strip keeps showing current team
- Display keeps updating
- Pending state changes queue up locally
- When connection restores, queued events flush to MQTT

If a player captures a point during a WiFi outage, the local node reflects that capture immediately. When connectivity returns, the dashboard catches up.

### MQTT Reliability Features

**QoS 1** for all state-change publishes — broker acknowledges receipt.

**Retained flag** on current-state messages — new subscribers (e.g., dashboards opened mid-game) immediately get the current state of every node without waiting.

**Last Will and Testament (LWT)** — each node tells the broker on connection: "if you stop hearing from me, publish `offline` on `airsoft/<type>/<id>/status`." This means the dashboard can show real-time online/offline status per node without any explicit polling.

**Heartbeats every 10-15 seconds** — each node publishes a small heartbeat message even when nothing has changed. Dashboard uses this to display connection health.

**Non-blocking reconnection** — the PubSubClient library does not auto-reconnect. The firmware checks connection status every loop iteration and triggers reconnection via a non-blocking timer (try every 5 seconds, don't block the game loop while waiting).

## Game Logic Details

### King of the Hill (Control Points)

Each control point has two team buttons and tracks cumulative hold time per team.

**Capture rules:**
- A player presses a team button while holding the button for the capture delay (2-3 seconds) to capture the point for their team
- If their team already holds the point: button press is ignored (prevents accidental resets)
- If the other team holds the point: this team takes over, the other team's timer stops accumulating
- Cumulative time persists across captures — both teams accumulate their total time held

**Why cumulative (not continuous-hold) model:**
- More forgiving — short captures still count toward your team
- More dramatic — late-game comebacks are possible
- Better for varied play styles — supports both aggressive contesting and defensive holding

**Display behavior:**
- Red display shows red team's cumulative hold time on this point
- Blue display shows blue team's cumulative hold time on this point
- Only the holding team's display is actively incrementing
- Format: MM:SS using the TM1637's center colon

**LED strip behavior:**
- Off / neutral pattern when no team has captured yet
- Solid color (or animated effect) of holding team
- Brief flash animation on capture transition

### Capture All Flags

Each flag node has two team buttons and tracks current ownership only — no timers.

**Capture rules:**
- Any team button press immediately changes ownership (or after a short capture delay)
- No cumulative tracking, no per-team state

**Win condition:**
- Detected by the central dashboard, not by individual nodes
- When all flags are simultaneously held by one team, dashboard declares victory and triggers audio announcement

**LED strip behavior:**
- Off / neutral when uncaptured
- Solid team color (with optional animation) when owned

### Classic CTF (Referee Buttons)

Referee buttons are placed at each team's spawn point. Referees physically observe captures and press buttons to register scoring events that the central system cannot otherwise detect.

**Button layout (recommended):**
- "Red team scored" button
- "Blue team scored" button
- Optional "undo" button to correct mistakes

**Behavior:**
- Each press publishes a scoring event to MQTT
- Dashboard maintains score, displays it prominently
- Audio announcement plays for each scoring event

**Alternative considered:** A small touchscreen display (e.g., LilyGO T-Display) showing live score and allowing +/- adjustments. More flexible but more complex. Recommend simple buttons for v1, upgrade if needed.

## Implementation Plan

### Phased Approach

Build in phases to avoid trying to debug everything at once.

**Phase 1: Single-node prototype, no network**
- One ESP32 on a breadboard
- Two buttons, two displays, one LED strip
- Implement local game state machine
- Validate: button presses are detected and debounced cleanly, displays show correct timers, LED strip changes color on capture, capture delay works correctly

**Phase 2: WiFi + MQTT**
- Add WiFi connection logic with auto-reconnect
- Connect to local Mosquitto broker (run on laptop initially)
- Publish state changes to MQTT topics
- Verify with MQTT Explorer or similar tool
- Add OTA update support
- Implement LWT and heartbeats

**Phase 3: Build the central server**
- Set up Raspberry Pi with Mosquitto, web server, audio service
- Build the dashboard (vanilla HTML/CSS/JS + WebSocket or SSE)
- Test with the one prototype node

**Phase 4: Multi-node testing**
- Build a second control point
- Verify both work simultaneously
- Test edge cases: simultaneous captures, network drops, etc.

**Phase 5: Build remaining nodes**
- Once design is proven, replicate for all remaining nodes
- Build flag nodes (simpler — no displays)
- Build referee buttons (simplest — no displays, short LED strip)

**Phase 6: Field deployment and testing**
- Mount enclosures at planned locations
- Verify WiFi signal strength at each location
- Add WiFi extenders or repositioning as needed
- Run test games, iterate on game logic and announcements

### What to Build First

When dev hardware is in hand, start with **WiFi + MQTT** before adding any I/O code:

1. Get the ESP32 connecting to WiFi reliably (including auto-reconnect on AP drops)
2. Get it publishing to a local MQTT broker
3. Verify reception with MQTT Explorer
4. Add OTA support
5. Add LWT and heartbeats

Only then add button input, then display output, then LED strip output. Build the network layer first because it's the highest-risk component — if WiFi/MQTT don't work reliably in your environment, everything else is moot.

## Audio Announcement Design

### Audio File Categories

- **Control point captures:** One file per control point per team. 5 points × 2 teams = 10 files. ("Red captures Alpha!", "Blue captures Alpha!", etc.)
- **Flag captures:** Same pattern. 5 flags × 2 teams = 10 files.
- **CTF scoring:** Either pre-generated common scores ("Red 1, Blue 0" through "Red 10, Blue 10") or modular pieces stitched together.
- **Game state events:** Start, end, 5-minute warning, 1-minute warning, overtime, etc.
- **System events:** Node offline, node online (quieter, informational).

### Voice Direction

- Use distinct voices per team if possible (e.g., commanding male for red, sharp female for blue) for instant audio recognition
- Keep announcements 2-3 seconds maximum — players won't catch long ones over field noise
- Use a brief attention-getting sound effect before each announcement (radio click, klaxon, tone)
- Maintain consistent phrasing: "[Team] captures [Point]!" pattern

### Playback Logic

- Audio queue in software — sequential playback, drop old queued items if queue grows too long
- Rate limiting per event type (e.g., max one announcement per control point per 10 seconds — prevents spam from rapid button toggling)
- Priority levels (game start/end > captures > online/offline notifications)

### Theme System (Future)

The infrastructure supports swappable audio packs — military, sci-fi, zombie, etc. Each theme is a folder of audio files with consistent naming. Dashboard selects active theme before game start.

## Site-Specific Notes

- Field WiFi is provided (no need to bring own AP, though a backup travel router or Pi-as-AP setup is wise)
- Indoor environment — IP65 LED strips and basic enclosures sufficient (no full weatherproofing needed)
- AC power available at every node location — no battery operation required
- ~100ft maximum distance from any node to AP, with wood walls (low signal loss) and drywall (moderate signal loss) in between
- One problem node has multiple drywall walls between it and the AP — may need a WiFi extender or higher-gain antenna for that location specifically

## Open Decisions

These haven't been finalized yet and need decisions during implementation:

- **Animation patterns for LED strips:** Solid color vs. breathing, sweep on capture, idle pattern when neutral. User has ideas for animations.
- **Exact "neutral" state representation:** Off, dim white, slow rainbow, alternating red/blue?
- **Idle behavior of displays:** Show "0000" or blanked?
- **Game timer:** Is there an overall game time limit shown somewhere (dashboard? per-node display?)?
- **Score display in CTF mode:** Just on dashboard, or also on referee nodes' LED strips?
- **Multiple game support:** Can multiple game modes run simultaneously, or only one active at a time?

## Build Quality Considerations

- Use the screw-terminal expansion bases on the ESP32s for permanent installations — never solder directly to module pins
- JST-SM connectors on LED strips for easy disconnection during maintenance
- Heat-shrink tubing on all solder joints
- Strain relief on all cable entries to enclosures
- Label every cable and every node clearly
- Keep a build log — when you build node 7 of 10, you won't remember what you did differently on node 2

## Lessons Already Learned

- CH340K boards need the CH341SER driver from WCH (driver name covers CH340/CH341 family despite the numerical mismatch)
- Power-only USB-C cables are a common gotcha — verify cables can do data before troubleshooting drivers
- VS Code + PlatformIO is the right development environment over the Arduino IDE — better refactoring, version control, multi-file project support
