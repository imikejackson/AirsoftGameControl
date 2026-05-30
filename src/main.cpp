//
// main.cpp — Airsoft Control Point System firmware entry point.
//
// This is the shared base across all node types. It brings up the non-blocking
// WiFi module, an e-paper status display, and the MQTT reporting/command
// channel; OTA, buttons, and LEDs layer on from here. The golden rule
// (CLAUDE.md): loop() must never block — no delay() — so buttons and the
// network stay responsive at all times. (The e-paper refresh is the one slow
// operation, and it only runs when the shown status actually changes.)
//
#include <Arduino.h>

#include "config.h"
#include "network.h"
#include "epaper.h"
#include "mqtt.h"
#include "ota.h"
#include "buttons.h"
#include "statusled.h"
#include "game_controlpoint.h"
#include "oled.h"

// Publish the current game state as a retained JSON payload (small, hand-built
// to avoid pulling ArduinoJson into main). Called on each ownership change.
static void publishGameState() {
  String payload = String("{\"owner\":\"") + teamName(gameOwner()) +
                   "\",\"red_s\":" + String(gameCumulativeMs(TEAM_RED) / 1000) +
                   ",\"blue_s\":" + String(gameCumulativeMs(TEAM_BLUE) / 1000) +
                   "}";
  mqttPublishState(payload);
}

// Handle an inbound MQTT command. Any payload containing "reset" zeroes the
// game (covers both this node's command topic and airsoft/game/command).
static void onMqttCommand(const String &topic, const String &payload) {
  Serial.printf("[cmd] %s -> %s\n", topic.c_str(), payload.c_str());
  if (payload.indexOf("reset") >= 0) gameReset();
}

// Single owner of the Serial reader: read one line and dispatch it to each
// module's command handler so they never race for input.
static void pollSerialCommands() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  if (handleNetworkSerialCommand(line)) return;
  if (handleMqttSerialCommand(line)) return;
  if (line == "reset") {
    gameReset();
    return;
  }
  if (line == "score") {
    Serial.printf("[game] owner=%s red=%lus blue=%lus\n", teamName(gameOwner()),
                  (unsigned long)(gameCumulativeMs(TEAM_RED) / 1000),
                  (unsigned long)(gameCumulativeMs(TEAM_BLUE) / 1000));
    return;
  }
  Serial.println("[cfg] commands: wifi <ssid> <pass> | nodeid <id> | netstatus "
                 "| mqtt <host> <port> | mqttstatus | reset | score");
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // brief settle so the first logs aren't lost; only in setup()
  Serial.println();
  Serial.println("=== Airsoft Control Point System ===");
  Serial.printf("node type: %s\n", NODE_TYPE_STR);

  // Networking first: a flaky display must never keep a node offline
  // (CLAUDE.md: WiFi/game must keep working regardless of peripherals).
  networkSetup();

  mqttSetup();
  mqttSetCommandHandler(onMqttCommand);

  otaSetup();     // arms once WiFi is up, inside otaLoop()

  buttonsSetup();
  statusLedSetup();
  gameSetup();    // after buttonsSetup: the game reads debounced button state

  // Prefer the OLED for the live display if one is wired; the e-paper is the
  // fallback. Both are initialized; only the chosen one is driven in loop().
  oledSetup();
  epaperSetup();
}

// Drive the onboard RGB from the GAME state: solid owner color when held, the
// capturing team's color BLINKING during the 2.5 s capture hold, off when
// neutral. Only writes the pixel when the color actually changes. (Bring-up
// indicator; real ownership color will come from the WS2812B strip module.)
static void updateStatusLed() {
  uint8_t r = 0, g = 0, b = 0;
  if (gameCaptureInProgress()) {
    const bool on = (millis() / 200) % 2;  // ~2.5 Hz blink while capturing
    if (on) (gameCapturingTeam() == TEAM_RED ? r : b) = 60;
  } else {
    const Team owner = gameOwner();
    if (owner == TEAM_RED) r = 60;
    else if (owner == TEAM_BLUE) b = 60;
  }
  static uint8_t lr = 1, lg = 1, lb = 1;  // impossible init -> first write
  if (r != lr || g != lg || b != lb) {
    lr = r; lg = g; lb = b;
    statusLedSetColor(r, g, b);
  }
}

// Refresh the e-paper game screen. A full refresh blocks ~4 s, so: redraw
// immediately on ownership change, otherwise only slowly AND only when no
// button is held (so a refresh can never interrupt a capture attempt).
static void updateGameDisplay(bool ownerChanged) {
  static unsigned long lastDraw = 0;
  const bool held = buttonPressed(TEAM_RED) || buttonPressed(TEAM_BLUE);
  if (!ownerChanged &&
      !(millis() - lastDraw >= GAME_EPAPER_REFRESH_MS && !held)) {
    return;
  }
  lastDraw = millis();
  epaperUpdateGame(nodeId(), gameOwner(), gameCumulativeMs(TEAM_RED) / 1000,
                   gameCumulativeMs(TEAM_BLUE) / 1000, wifiConnected(),
                   wifiIpString());
}

void loop() {
  networkLoop();        // drive WiFi connect/reconnect state machine
  otaLoop();            // service OTA listener (arms once WiFi is up)
  mqttLoop();           // drive MQTT connect/reconnect + service messages
  pollSerialCommands(); // runtime provisioning (wifi/nodeid/mqtt/...)

  buttonsLoop();   // debounce + button edge events
  gameLoop();      // capture countdown, ownership transfer, cumulative timers

  // On an ownership change (capture or reset), report it over MQTT.
  const bool ownerChanged = gameConsumeOwnershipChanged();
  if (ownerChanged) publishGameState();

  updateStatusLed();  // onboard RGB reflects ownership/capture

  // Live game display: OLED if present (fast, live-ticking), else e-paper.
  if (oledPresent()) {
    oledShowGame(nodeId(), gameOwner(), gameCumulativeMs(TEAM_RED),
                 gameCumulativeMs(TEAM_BLUE), gameCaptureInProgress(),
                 gameCapturingTeam(), gameCaptureElapsedMs());
  } else {
    updateGameDisplay(ownerChanged);  // e-paper game screen (throttled)
  }

  // Lightweight heartbeat to Serial so we can confirm the loop is alive and
  // watch connection state without blocking. Non-blocking millis() timer.
  static unsigned long lastBeat = 0;
  if (millis() - lastBeat >= 5000) {
    lastBeat = millis();
    Serial.printf("[hb] wifi: %s | mqtt: %s\n",
                  wifiStatusString().c_str(), mqttStatusString().c_str());
  }

  // Next: WS2812B ownership strip and TM1637 timer displays will consume the
  // same game state. Everything in this loop must stay non-blocking.
}
