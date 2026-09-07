#pragma once
//
// leds.h — WS2812B ownership strip (FastLED) on PIN_LED_DATA (GPIO 5).
//
// Consumes the same game state as the LCD/RGB: solid team color when a team
// owns the point, a progress-fill in the capturing team's color during the
// 2.5s hold, and a dim idle glow when neutral. Power is injected externally;
// the ESP32 only drives data + shares ground.
//
#include "types.h"

void ledsSetup();

// Call every loop() iteration. Self-throttles to a sane frame rate.
void ledsShow(Team owner, bool capturing, Team capturingTeam,
              uint32_t captureElapsedMs, bool running);

// Onboard status pixel (GPIO 2). Driven through FastLED — NOT neopixelWrite —
// so a single RMT owner manages every WS2812 on the board (mixing the two RMT
// drivers makes FastLED fail to bind the strip pin). statusled.cpp delegates
// here. Safe to call after ledsSetup().
void ledsSetStatus(uint8_t r, uint8_t g, uint8_t b);

// Sleep animation: a scrolling rainbow chase across the whole strip. Call every
// loop while the node is asleep (self-throttles). The power cap still applies.
void ledsRainbow();

// Rush "locked" look: dim amber standby breathing for a pending bomb, or a
// solid dim red for a detonated one. Call every loop while the box is locked.
void ledsShowLocked(bool detonated);

// Rush active-bomb look: a progress fill (pct 0-100) toward detonation in the
// attacking team's color over a dim base. Call every loop on the active box.
void ledsShowArm(uint8_t pct, Team attacker);
