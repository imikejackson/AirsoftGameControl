#pragma once
//
// oled.h — Optional SSD1306 128x64 I2C OLED for the LIVE game display.
//
// Unlike the e-paper (~4s blocking refresh), the OLED updates in ~30ms, so it
// shows live-ticking cumulative timers and a real-time capture progress bar.
// Auto-detected at boot: if found it becomes the live display; if not, the
// caller falls back to the e-paper. The "yellow/blue" panels are monochrome
// with a fixed color split, so team color lives on the LEDs, not here.
//
#include "types.h"

// Initialize I2C and probe for the panel. Returns true if an SSD1306 answered.
bool oledSetup();

// Was a panel detected? (Caller uses this to pick OLED vs e-paper.)
bool oledPresent();

// Render the live game screen. Cheap to call every loop — it no-ops if no
// panel is present and otherwise throttles itself to OLED_REFRESH_MS. Times are
// passed in milliseconds so it can tick live and draw the capture bar.
void oledShowGame(const String &nodeName, Team owner, uint32_t redMs,
                  uint32_t blueMs, bool capturing, Team capturingTeam,
                  uint32_t captureElapsedMs);
