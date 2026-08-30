//
// main.cpp — Airsoft Control Point System firmware entry point.
//
// This is the shared base across all node types. It brings up the non-blocking
// WiFi module, an OLED live display, and the MQTT reporting/command channel;
// OTA, buttons, and LEDs layer on from here. The golden rule (CLAUDE.md):
// loop() must never block — no delay() — so buttons and the network stay
// responsive at all times.
//
#include <Arduino.h>
#include <ArduinoJson.h>

#include "config.h"
#include "network.h"
#include "mqtt.h"
#include "ota.h"
#include "buttons.h"
#include "statusled.h"
#include "game_controlpoint.h"
#include "oled.h"
#include "lcd.h"
#include "leds.h"

// Publish the current game state as a retained JSON payload (small, hand-built
// to avoid pulling ArduinoJson into main). Called on each ownership change.
static void publishGameState() {
  String payload = String("{\"owner\":\"") + teamName(gameOwner()) +
                   "\",\"red_s\":" + String(gameCumulativeMs(TEAM_RED) / 1000) +
                   ",\"blue_s\":" + String(gameCumulativeMs(TEAM_BLUE) / 1000) +
                   ",\"running\":" + (gameRunning() ? "true" : "false") + "}";
  mqttPublishState(payload);
}

// Handle an inbound MQTT command. The retained airsoft/game/state carries the
// authoritative run state ({"running":true/false}); the command topics (this
// node's, or airsoft/game/command) carry actions: reset / start / stop.
static void onMqttCommand(const String &topic, const String &payload) {
  Serial.printf("[cmd] %s -> %s\n", topic.c_str(), payload.c_str());
  if (topic == "airsoft/game/state") {
    JsonDocument doc;
    if (deserializeJson(doc, payload)) return;  // bad JSON -> ignore
    long rem = doc["remaining_s"] | -1L;
    if (rem >= 0) gameSetCountdown((uint32_t)rem * 1000UL);
    gameSetRunning(doc["running"] | false);
    return;
  }
  if (payload.indexOf("reset") >= 0) gameReset();
  else if (payload.indexOf("start") >= 0) gameSetRunning(true);
  else if (payload.indexOf("stop") >= 0) gameSetRunning(false);
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

// Boot-time WiFi network picker on the LCD. Shows the preset networks; the Red
// and Blue buttons choose one. With exactly two presets, Red picks the first
// and Blue the second; with more, Red cycles the highlight and Blue confirms.
// If no button is pressed within WIFI_PICKER_TIMEOUT_MS the last-used network is
// kept (returns -1 = "no change"), so an unattended power-cycle just reconnects.
// Blocking is fine here: it runs in setup() before the radio/game come up.
static int runWifiPicker() {
  const int count = networkPresetCount();
  if (count <= 1 || WIFI_PICKER_TIMEOUT_MS == 0) return -1;  // nothing to choose

  const int n = (count > 8) ? 8 : count;
  const char *labels[8];
  const char *ssids[8];
  for (int i = 0; i < n; i++) {
    labels[i] = networkPresetLabel(i);
    ssids[i]  = networkPresetSsid(i);
  }

  int sel = networkLastPresetIndex();
  if (sel >= n) sel = 0;

  // Prime edge detection so a button already held at power-on doesn't register.
  buttonsLoop();
  bool lastRed  = buttonPressed(TEAM_RED);
  bool lastBlue = buttonPressed(TEAM_BLUE);

  Serial.println("[wifi] boot picker: Red/Blue to choose network");
  const unsigned long start = millis();
  int chosen = -1;
  for (;;) {
    buttonsLoop();
    const bool red  = buttonPressed(TEAM_RED);
    const bool blue = buttonPressed(TEAM_BLUE);
    const bool redEdge  = red  && !lastRed;
    const bool blueEdge = blue && !lastBlue;
    lastRed = red; lastBlue = blue;

    if (n == 2) {
      if (redEdge)  { chosen = 0; break; }
      if (blueEdge) { chosen = 1; break; }
    } else {
      if (redEdge)  sel = (sel + 1) % n;
      if (blueEdge) { chosen = sel; break; }
    }

    const unsigned long el = millis() - start;
    if (el >= WIFI_PICKER_TIMEOUT_MS) { chosen = -1; break; }
    const int secs = (int)((WIFI_PICKER_TIMEOUT_MS - el + 999) / 1000);
    lcdShowWifiPicker(labels, ssids, n, sel, secs);
    delay(15);  // gentle poll; setup context, nothing else running yet
  }
  Serial.printf("[wifi] picker result: %d\n", chosen);
  return chosen;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // brief settle so the first logs aren't lost; only in setup()
  Serial.println();
  Serial.println("=== Airsoft Control Point System ===");
  Serial.printf("node type: %s\n", NODE_TYPE_STR);

  // Buttons + LCD first so the boot WiFi picker can use them. The picker has a
  // bounded timeout, so it can't keep a node offline (CLAUDE.md: WiFi/game must
  // keep working regardless of peripherals).
  buttonsSetup();
  lcdSetup();     // ST7789 control-point display (team color + big timers)

  // Let the operator pick the WiFi network on the LCD (Red/Blue); otherwise keep
  // the last-used network after the timeout. Applied before the radio starts.
  {
    const int sel = runWifiPicker();
    if (sel >= 0) networkApplyPreset(sel);
  }

  networkSetup();  // connect with the (possibly just-picked) credentials
  mqttSetup();
  mqttSetCommandHandler(onMqttCommand);
  otaSetup();      // arms once WiFi is up, inside otaLoop()

  statusLedSetup();
  gameSetup();     // after buttonsSetup: the game reads debounced button state

  oledSetup();     // live display; the game still runs headless if absent
  ledsSetup();     // WS2812B ownership strip on GPIO 5 (external-powered)
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

void loop() {
  networkLoop();        // drive WiFi connect/reconnect state machine
  otaLoop();            // service OTA listener (arms once WiFi is up)
  mqttLoop();           // drive MQTT connect/reconnect + service messages
  pollSerialCommands(); // runtime provisioning (wifi/nodeid/mqtt/...)

  buttonsLoop();   // debounce + button edge events
  gameLoop();      // capture countdown, ownership transfer, cumulative timers

  // On a game-state change (capture, reset, or start/stop), report over MQTT.
  if (gameConsumeStateChanged()) publishGameState();

  updateStatusLed();  // onboard RGB reflects ownership/capture

  // WS2812B ownership strip: solid team color when held, capturing-team
  // progress-fill during the hold, dim idle glow when neutral.
  ledsShow(gameOwner(), gameCaptureInProgress(), gameCapturingTeam(),
           gameCaptureElapsedMs(), gameRunning());

  // Live game displays. Both are driven (different buses): the OLED (I2C) and
  // the ST7789 LCD (SPI). Each throttles itself and no-ops if not connected.
  oledShowGame(nodeId(), gameOwner(), gameCumulativeMs(TEAM_RED),
               gameCumulativeMs(TEAM_BLUE), gameCaptureInProgress(),
               gameCapturingTeam(), gameCaptureElapsedMs());
  const int32_t remainingS =
      gameHasClock() ? (int32_t)(gameRemainingMs() / 1000) : -1;
  lcdShowGame(nodeId(), gameOwner(), gameCumulativeMs(TEAM_RED),
              gameCumulativeMs(TEAM_BLUE), gameCaptureInProgress(),
              gameCapturingTeam(), gameCaptureElapsedMs(), wifiConnected(),
              wifiIpString(), gameRunning(), remainingS);

  // Lightweight heartbeat to Serial so we can confirm the loop is alive and
  // watch connection state without blocking. Non-blocking millis() timer.
  static unsigned long lastBeat = 0;
  if (millis() - lastBeat >= 5000) {
    lastBeat = millis();
    Serial.printf("[hb] wifi: %s | mqtt: %s\n",
                  wifiStatusString().c_str(), mqttStatusString().c_str());
  }
}
