//
// ota.cpp — ArduinoOTA wrapper.
//
#include "ota.h"
#include "config.h"
#include "network.h"
#include "secrets.h"

#include <ArduinoOTA.h>

namespace {
bool g_armed      = false;  // ArduinoOTA.begin() has been called this WiFi session
bool g_inProgress = false;  // an update transfer is underway
}  // namespace

void otaSetup() {
  ArduinoOTA.setHostname(nodeHostname().c_str());

  // Optional auth: set OTA_PASSWORD in secrets.h (empty string disables it).
  if (strlen(OTA_PASSWORD) > 0) {
    ArduinoOTA.setPassword(OTA_PASSWORD);
  }

  ArduinoOTA.onStart([]() {
    g_inProgress = true;
    const char *what =
        (ArduinoOTA.getCommand() == U_FLASH) ? "firmware" : "filesystem";
    Serial.printf("[ota] update starting (%s)\n", what);
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("\n[ota] update complete; rebooting");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("[ota] %u%%\r", (progress * 100) / total);
  });
  ArduinoOTA.onError([](ota_error_t error) {
    g_inProgress = false;
    Serial.printf("[ota] error %u\n", error);
  });
}

void otaLoop() {
  if (!wifiConnected()) {
    g_armed = false;  // re-arm after the next reconnect
    return;
  }

  if (!g_armed) {
    ArduinoOTA.begin();  // also sets up the mDNS responder for discovery
    g_armed = true;
    Serial.printf("[ota] ready: %s.local (port 3232)\n",
                  nodeHostname().c_str());
  }

  ArduinoOTA.handle();
}

bool otaInProgress() { return g_inProgress; }
