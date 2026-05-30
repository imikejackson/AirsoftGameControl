#pragma once
//
// statusled.h — The dev board's single onboard WS2812/NeoPixel (GPIO 2), used
// as a status/feedback indicator. Distinct from the WS2812B ownership strip
// (PIN_LED_DATA) that the LED module will drive later.
//
// Driven via the ESP32 core's neopixelWrite() — no external library.
//
#include "types.h"
#include <stdint.h>

// Call once in setup(). Turns the pixel off.
void statusLedSetup();

// Set an explicit RGB color (0-255 each). Values are kept modest by callers so
// the pixel isn't blinding.
void statusLedSetColor(uint8_t r, uint8_t g, uint8_t b);

// Convenience: show a team color (RED -> red, BLUE -> blue, NONE -> off).
void statusLedShowTeam(Team team);
