//
// statusled.cpp — Onboard WS2812 status pixel.
//
#include "statusled.h"
#include "config.h"
#include "leds.h"

#include <Arduino.h>

// Modest brightness so the bare pixel isn't blinding to look at.
namespace {
constexpr uint8_t kLevel = 60;
}

void statusLedSetup() {
  // No-op: the onboard pixel is a FastLED controller now, registered and
  // blanked in ledsSetup() (which runs after this). Driving it here — before
  // FastLED is initialized — would be a no-op at best, so we defer entirely.
}

void statusLedSetColor(uint8_t r, uint8_t g, uint8_t b) {
  // Delegate to FastLED so a single RMT driver owns every WS2812 on the board.
  ledsSetStatus(r, g, b);
}

void statusLedShowTeam(Team team) {
  switch (team) {
    case TEAM_RED:  statusLedSetColor(kLevel, 0, 0); break;
    case TEAM_BLUE: statusLedSetColor(0, 0, kLevel); break;
    default:        statusLedSetColor(0, 0, 0); break;
  }
}
