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

// Handle an inbound MQTT command. Game logic (reset, mode changes, etc.) will
// hang off this; for now we log so we can confirm the command path works.
static void onMqttCommand(const String &topic, const String &payload) {
  Serial.printf("[cmd] %s -> %s\n", topic.c_str(), payload.c_str());
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
  Serial.println("[cfg] commands: wifi <ssid> <pass> | nodeid <id> | "
                 "netstatus | mqtt <host> <port> | mqttstatus");
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

  epaperSetup();  // draws the initial status screen
}

// Drive the onboard RGB from the live button state: red/blue while held, both
// -> magenta, neither -> off. Only writes the pixel when the combination
// changes. (A bring-up indicator; real team/ownership color will come from the
// WS2812B strip module.)
static void updateStatusLedFromButtons() {
  const int code = (buttonPressed(TEAM_RED) ? 1 : 0) |
                   (buttonPressed(TEAM_BLUE) ? 2 : 0);
  static int lastCode = -1;
  if (code == lastCode) return;
  lastCode = code;
  switch (code) {
    case 1:  statusLedSetColor(60, 0, 0);  break;  // red held
    case 2:  statusLedSetColor(0, 0, 60);  break;  // blue held
    case 3:  statusLedSetColor(60, 0, 60); break;  // both held -> magenta
    default: statusLedSetColor(0, 0, 0);   break;  // none -> off
  }
}

void loop() {
  networkLoop();        // drive WiFi connect/reconnect state machine
  otaLoop();            // service OTA listener (arms once WiFi is up)
  mqttLoop();           // drive MQTT connect/reconnect + service messages
  pollSerialCommands(); // runtime provisioning (wifi/nodeid/mqtt/...)

  buttonsLoop();                 // debounce + button edge events
  updateStatusLedFromButtons();  // onboard RGB reflects button state

  // Update the e-paper only when identity/network status changes (the call is
  // cheap until something differs, then it does one ~4 s refresh).
  epaperUpdateStatus(nodeId(), nodeTypeStr(), wifiConnected(),
                     wifiSsid(), wifiIpString());

  // Lightweight heartbeat to Serial so we can confirm the loop is alive and
  // watch connection state without blocking. Non-blocking millis() timer.
  static unsigned long lastBeat = 0;
  if (millis() - lastBeat >= 5000) {
    lastBeat = millis();
    Serial.printf("[hb] wifi: %s | mqtt: %s\n",
                  wifiStatusString().c_str(), mqttStatusString().c_str());
  }

  // Game logic (capture hold, ownership/timers, strip color) layers on top of
  // the debounced buttons above. Everything in this loop must stay non-blocking.
}
