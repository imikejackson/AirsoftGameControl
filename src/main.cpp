//
// main.cpp — Airsoft Control Point System firmware entry point.
//
// This is the shared base across all node types. It brings up the non-blocking
// WiFi module and an e-paper status display; MQTT, OTA, buttons, and LEDs layer
// on from here. The golden rule (CLAUDE.md): loop() must never block — no
// delay() — so buttons and the network stay responsive at all times. (The
// e-paper refresh is the one slow operation, and it only runs when the shown
// status actually changes — see epaper.cpp.)
//
#include <Arduino.h>

#include "config.h"
#include "network.h"
#include "epaper.h"

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // brief settle so the first logs aren't lost; only in setup()
  Serial.println();
  Serial.println("=== Airsoft Control Point System ===");
  Serial.printf("node type: %s\n", NODE_TYPE_STR);

  // Networking first: a flaky display must never keep a node offline
  // (CLAUDE.md: WiFi/game must keep working regardless of peripherals).
  networkSetup();

  epaperSetup();  // draws the initial status screen
}

void loop() {
  networkLoop();        // drive WiFi connect/reconnect state machine
  handleSerialConfig(); // accept "wifi <ssid> <pass>" etc. over Serial

  // Update the e-paper only when identity/network status changes (the call is
  // cheap until something differs, then it does one ~4 s refresh).
  epaperUpdateStatus(nodeId(), nodeTypeStr(), wifiConnected(),
                     wifiSsid(), wifiIpString());

  // Lightweight heartbeat to Serial so we can confirm the loop is alive and
  // watch connection state without blocking. Non-blocking millis() timer.
  static unsigned long lastBeat = 0;
  if (millis() - lastBeat >= 5000) {
    lastBeat = millis();
    Serial.printf("[hb] %s\n", wifiStatusString().c_str());
  }

  // Game logic (buttons / displays / LEDs) will be added here. Everything in
  // this loop must remain non-blocking.
}
