//
// leds.cpp — WS2812B ownership strip via FastLED.
//
#include "leds.h"
#include "config.h"

#include <FastLED.h>

namespace {

CRGB          g_leds[NUM_LEDS];
CRGB          g_status[1];  // onboard status pixel (GPIO 2)
unsigned long g_lastFrame = 0;
const unsigned long FRAME_MS = 40;  // ~25 fps

CRGB teamColor(Team t) {
  return (t == TEAM_RED) ? CRGB::Red : (t == TEAM_BLUE) ? CRGB::Blue : CRGB::Black;
}

}  // namespace

void ledsSetup() {
  // FastLED owns EVERY WS2812 on the board: the ownership strip on GPIO 5 and
  // the onboard status pixel on GPIO 2. Registering both here (instead of using
  // the core's neopixelWrite for the onboard one) keeps a single RMT driver in
  // charge — mixing FastLED's RMT5 driver with neopixelWrite makes the strip
  // fail to bind ("invalid pin" / bogus GPIO).
  FastLED.addLeds<WS2812B, PIN_LED_DATA, GRB>(g_leds, NUM_LEDS);
  FastLED.addLeds<WS2812B, PIN_STATUS_RGB, GRB>(g_status, 1);
  FastLED.setBrightness(LED_BRIGHTNESS);

  // Hard power budget: the strip runs off a 5V / 5A (25W) supply shared with the
  // ESP32. A full-white frame at full brightness is ~60mA/LED, so ~80 LEDs would
  // already max the supply -- more than that and the rail sags into a brownout.
  // FastLED auto-scales overall brightness on every show() so total draw never
  // exceeds this cap (5V, 4500mA leaves ~500mA headroom for the ESP32). This
  // lets us wire a long strip safely: bright effects just get throttled instead
  // of crashing the supply. Raise the mA only with a bigger PSU.
  FastLED.setMaxPowerInVoltsAndMilliamps(5, LED_MAX_MILLIAMPS);
  Serial.printf("[leds] FastLED init: %d px strip on GPIO %d, status on GPIO %d\n",
                NUM_LEDS, PIN_LED_DATA, PIN_STATUS_RGB);

  // Boot self-test: sweep the whole strip red -> green -> blue -> off. Lets you
  // confirm at a glance that the strip is alive, wired the right way, the length
  // matches NUM_LEDS, and the color order is correct -- all before any game
  // logic (or a paused clock) can leave it dark. delay() is fine here in setup.
  const CRGB probe[] = {CRGB::Red, CRGB::Green, CRGB::Blue};
  for (const CRGB &c : probe) {
    fill_solid(g_leds, NUM_LEDS, c);
    g_status[0] = c;
    FastLED.show();
    delay(400);
  }
  fill_solid(g_leds, NUM_LEDS, CRGB::Black);
  g_status[0] = CRGB::Black;
  FastLED.show();
}

void ledsSetStatus(uint8_t r, uint8_t g, uint8_t b) {
  g_status[0] = CRGB(r, g, b);
  FastLED.show();
}

void ledsRainbow() {
  if ((millis() - g_lastFrame) < FRAME_MS) return;
  g_lastFrame = millis();
  // deltaHue 4 => a full spectrum roughly every 64 LEDs (a few bands on a long
  // strip). Scroll the pattern one LED per CHASE_STEP_MS so it chases at the
  // same speed as the capture comet. The FastLED power cap auto-dims the frame
  // if it would draw too much.
  const uint8_t deltaHue = 4;
  const uint8_t startHue = (uint8_t)((millis() / CHASE_STEP_MS) * deltaHue);
  fill_rainbow(g_leds, NUM_LEDS, startHue, deltaHue);
  g_status[0] = CRGB::Black;  // onboard pixel off while asleep
  FastLED.show();
}

void ledsShowLocked(bool detonated) {
  if ((millis() - g_lastFrame) < FRAME_MS) return;
  g_lastFrame = millis();
  if (detonated) {
    fill_solid(g_leds, NUM_LEDS, CRGB(70, 0, 0));   // solid dim red = blown
  } else {
    const uint8_t b = beatsin8(15, 6, 44);          // amber standby breathing
    fill_solid(g_leds, NUM_LEDS, CRGB(b, (uint8_t)(b * 45 / 100), 0));
  }
  g_status[0] = CRGB::Black;
  FastLED.show();
}

void ledsShowArm(uint8_t pct, Team attacker) {
  if ((millis() - g_lastFrame) < FRAME_MS) return;
  g_lastFrame = millis();
  if (pct > 100) pct = 100;
  CRGB c = teamColor(attacker);
  if (c == CRGB(0, 0, 0)) c = CRGB(160, 90, 0);   // fallback amber if unknown
  CRGB base = c;
  base.nscale8_video(28);                          // dim attacker base
  const int lit = (int)((long)NUM_LEDS * pct / 100);
  for (int i = 0; i < NUM_LEDS; i++) g_leds[i] = (i < lit) ? c : base;
  g_status[0] = c;                                 // onboard pixel = attacker color
  FastLED.show();
}

void ledsShow(Team owner, bool capturing, Team capturingTeam,
              uint32_t captureElapsedMs, bool running) {
  if ((millis() - g_lastFrame) < FRAME_MS) return;
  g_lastFrame = millis();

  if (capturing) {
    // Progress-fill in the capturing team's color as the 2.5s hold advances.
    uint32_t pct = captureElapsedMs * 100 / CAPTURE_HOLD_MS;
    if (pct > 100) pct = 100;
    const int lit = (int)((long)NUM_LEDS * pct / 100);
    const CRGB c = teamColor(capturingTeam);
    for (int i = 0; i < NUM_LEDS; i++) {
      g_leds[i] = (i < lit) ? c : CRGB(4, 4, 4);
    }
  } else if (owner != TEAM_NONE) {
    CRGB c = teamColor(owner);
    if (!running) {
      // Paused / game over: static dimmed color so it reads as "frozen".
      c.nscale8_video(70);
      fill_solid(g_leds, NUM_LEDS, c);
    } else {
      // Active ownership: a bright comet chases along a dim team-color base.
      // The base keeps the strip unmistakably team-colored; the comet adds
      // motion. Saturating add so the tail glows over the base (no dark wake).
      CRGB base = c;
      base.nscale8_video(CHASE_BASE_SCALE);
      fill_solid(g_leds, NUM_LEDS, base);
      // A train of evenly-tiled comets. Spacing by NUM_LEDS/comets (rather than
      // raw CHASE_SPACING) keeps the gaps uniform across the wrap seam.
      int comets = NUM_LEDS / CHASE_SPACING;
      if (comets < 1) comets = 1;
      const int spacing = NUM_LEDS / comets;
      const int head = (int)((millis() / CHASE_STEP_MS) % NUM_LEDS);
      for (int cmt = 0; cmt < comets; cmt++) {
        const int h = (head + cmt * spacing) % NUM_LEDS;
        for (int i = 0; i < CHASE_TAIL; i++) {
          const int p = (h - i + NUM_LEDS) % NUM_LEDS;
          const uint8_t f = 255 - (uint8_t)(i * 255 / CHASE_TAIL);  // bright head -> dim tail
          CRGB seg = c;
          seg.nscale8_video(f);
          g_leds[p] += seg;
        }
      }
    }
  } else {
    // Neutral (no owner), a breathing glow: WHITE while idle between rounds,
    // GREEN once the round is live and the point is up for grabs.
    const uint8_t b = beatsin8(20, 30, 140);
    fill_solid(g_leds, NUM_LEDS, running ? CRGB(0, b, 0) : CRGB(b, b, b));
  }
  FastLED.show();
}
