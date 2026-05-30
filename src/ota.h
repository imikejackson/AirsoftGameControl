#pragma once
//
// ota.h — Over-the-air firmware updates (ArduinoOTA).
//
// CLAUDE.md mandates OTA from day one: once nodes are sealed in enclosures,
// USB access is impractical. This wraps ArduinoOTA so updates can be pushed
// over WiFi:  pio run -e esp32dev_ota -t upload --upload-port <node-ip>
//
// Non-blocking: otaLoop() services the OTA listener each iteration and only
// blocks while an update is actually being received (which is fine — the node
// is intentionally busy reflashing then). OTA is armed once WiFi is up and is
// re-armed automatically after a reconnect.
//
#include <Arduino.h>

// Configure hostname / password / callbacks. Call once in setup(), after
// networkSetup() (it reads the node hostname).
void otaSetup();

// Call every loop() iteration. Arms ArduinoOTA the first time WiFi is up, then
// services the listener. Re-arms after a WiFi drop/reconnect.
void otaLoop();

// True while an update transfer is in progress (other subsystems can use this
// to stand down — e.g. skip slow e-paper refreshes).
bool otaInProgress();
