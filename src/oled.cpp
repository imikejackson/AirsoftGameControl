//
// oled.cpp — SSD1306 live game display.
//
#include "oled.h"
#include "config.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

namespace {

Adafruit_SSD1306 g_oled(OLED_WIDTH, OLED_HEIGHT, &Wire, /*reset=*/-1);
bool          g_present  = false;
unsigned long g_lastDraw = 0;

String fmtTime(uint32_t ms) {
  const uint32_t s = ms / 1000;
  char buf[16];
  snprintf(buf, sizeof(buf), "%lu:%02lu", (unsigned long)(s / 60),
           (unsigned long)(s % 60));
  return String(buf);
}

const char *ownerLabel(Team owner) {
  switch (owner) {
    case TEAM_RED:  return "RED";
    case TEAM_BLUE: return "BLUE";
    default:        return "NEUTRAL";
  }
}

}  // namespace

bool oledSetup() {
  Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);
  Wire.setClock(400000);  // fast I2C for snappy refreshes

  // Real presence check: probe the bus for an ACK at the panel's address.
  // Adafruit_SSD1306::begin() returns true even with NO panel connected (it
  // only checks buffer allocation, not the I2C ACK), so without this the
  // e-paper fallback would never trigger.
  Wire.beginTransmission(OLED_I2C_ADDR);
  if (Wire.endTransmission() != 0) {
    g_present = false;
    Serial.println("[oled] no panel on I2C bus — falling back to e-paper");
    return false;
  }

  g_present = g_oled.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR);
  if (g_present) {
    g_oled.clearDisplay();
    g_oled.setTextColor(SSD1306_WHITE);
    g_oled.setTextSize(1);
    g_oled.setCursor(0, 0);
    g_oled.println("Airsoft CP");
    g_oled.display();
    Serial.println("[oled] SSD1306 detected — using OLED for live display");
  } else {
    Serial.println("[oled] begin() failed — falling back to e-paper");
  }
  return g_present;
}

bool oledPresent() { return g_present; }

void oledShowGame(const String &nodeName, Team owner, uint32_t redMs,
                  uint32_t blueMs, bool capturing, Team capturingTeam,
                  uint32_t captureElapsedMs) {
  if (!g_present) return;
  if ((millis() - g_lastDraw) < OLED_REFRESH_MS) return;
  g_lastDraw = millis();

  String name = nodeName;
  name.toUpperCase();

  g_oled.clearDisplay();

  // --- Yellow strip (rows 0-15): node name + version, then status line ------
  g_oled.setTextSize(1);
  g_oled.setCursor(0, 0);
  g_oled.print(name);

  String ver = "v" + String(FIRMWARE_VERSION);
  g_oled.setCursor(OLED_WIDTH - (int)ver.length() * 6, 0);
  g_oled.print(ver);

  g_oled.setCursor(0, 8);
  if (capturing) {
    uint32_t pct = captureElapsedMs * 100 / CAPTURE_HOLD_MS;
    if (pct > 100) pct = 100;
    g_oled.print("CAP ");
    g_oled.print(ownerLabel(capturingTeam));
    g_oled.print(" ");
    g_oled.print(pct);
    g_oled.print("%");
  } else {
    g_oled.print("OWNER: ");
    g_oled.print(ownerLabel(owner));
  }

  // --- Blue area (rows 16-63): large live timers ----------------------------
  g_oled.setTextSize(2);
  g_oled.setCursor(0, 24);
  g_oled.print("R ");
  g_oled.print(fmtTime(redMs));
  g_oled.setCursor(0, 46);
  g_oled.print("B ");
  g_oled.print(fmtTime(blueMs));

  // Capture progress bar across the very bottom during a capture attempt.
  if (capturing) {
    uint32_t w = captureElapsedMs * OLED_WIDTH / CAPTURE_HOLD_MS;
    if (w > OLED_WIDTH) w = OLED_WIDTH;
    g_oled.fillRect(0, 62, (int)w, 2, SSD1306_WHITE);
  }

  g_oled.display();
}
