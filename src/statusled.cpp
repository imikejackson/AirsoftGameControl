//
// statusled.cpp — Onboard WS2812 status pixel.
//
#include "statusled.h"
#include "config.h"

#include <Arduino.h>

// Modest brightness so the bare pixel isn't blinding to look at.
namespace {
constexpr uint8_t kLevel = 60;
}

void statusLedSetup() {
  // neopixelWrite() configures the pin/RMT on first use; just blank it.
  statusLedSetColor(0, 0, 0);
}

void statusLedSetColor(uint8_t r, uint8_t g, uint8_t b) {
  // Core helper drives a single WS2812 (handles GRB ordering internally).
  neopixelWrite(PIN_STATUS_RGB, r, g, b);
}

void statusLedShowTeam(Team team) {
  switch (team) {
    case TEAM_RED:  statusLedSetColor(kLevel, 0, 0); break;
    case TEAM_BLUE: statusLedSetColor(0, 0, kLevel); break;
    default:        statusLedSetColor(0, 0, 0); break;
  }
}
