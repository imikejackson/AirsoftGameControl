#pragma once
//
// lcd.h — 2" ST7789 240x320 IPS LCD: the control-point game display.
//
// Full color, so the whole screen is filled with the controlling team's color
// (red / blue / dark for neutral) for instant at-a-distance readability, with
// large live-ticking cumulative timers and a capture progress bar. Hardware SPI
// on the VSPI bus; pins in config.h. There's no presence probe (SPI has no
// ACK), so the caller just always drives it — writes no-op harmlessly if it's
// not connected.
//
#include "types.h"

void lcdSetup();

// Render the live game screen. Cheap to call every loop — throttles itself to
// LCD_REFRESH_MS and only repaints fields whose values changed (no flicker).
void lcdShowGame(const String &nodeName, Team owner, uint32_t redMs,
                 uint32_t blueMs, bool capturing, Team capturingTeam,
                 uint32_t captureElapsedMs, bool connected, const String &ip,
                 bool running, int32_t remainingS);
