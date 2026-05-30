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

  epaperSetup();  // draws the initial status screen
}

void loop() {
  networkLoop();        // drive WiFi connect/reconnect state machine
  otaLoop();            // service OTA listener (arms once WiFi is up)
  mqttLoop();           // drive MQTT connect/reconnect + service messages
  pollSerialCommands(); // runtime provisioning (wifi/nodeid/mqtt/...)

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

  // Game logic (buttons / displays / LEDs) will be added here. Everything in
  // this loop must remain non-blocking.
}
