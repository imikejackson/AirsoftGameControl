//
// buttons.cpp — Debounced button implementation.
//
// Standard time-based debounce: a raw reading must hold steady for
// BUTTON_DEBOUNCE_MS before we accept it as the new stable state. Active-low,
// so a press reads LOW (pin pulled to GND) and we invert to "pressed = true".
//
#include "buttons.h"
#include "config.h"

namespace {

struct Button {
  uint8_t       pin;
  Team          team;
  bool          stable;       // accepted debounced state (true = pressed)
  bool          lastReading;  // most recent raw reading
  unsigned long lastChangeMs; // when the raw reading last changed
};

Button g_buttons[] = {
    {PIN_BTN_RED, TEAM_RED, false, false, 0},
    {PIN_BTN_BLUE, TEAM_BLUE, false, false, 0},
};
constexpr size_t kNumButtons = sizeof(g_buttons) / sizeof(g_buttons[0]);

ButtonEventHandler g_handler = nullptr;

inline bool rawPressed(uint8_t pin) { return digitalRead(pin) == LOW; }

}  // namespace

void buttonsSetup() {
  for (auto &b : g_buttons) {
    pinMode(b.pin, INPUT_PULLUP);
    b.lastReading  = rawPressed(b.pin);
    b.stable       = b.lastReading;
    b.lastChangeMs = millis();
  }
}

void buttonsLoop() {
  const unsigned long now = millis();
  for (auto &b : g_buttons) {
    const bool reading = rawPressed(b.pin);

    if (reading != b.lastReading) {
      b.lastReading  = reading;
      b.lastChangeMs = now;  // reset the debounce timer on any bounce
    }

    if ((now - b.lastChangeMs) >= BUTTON_DEBOUNCE_MS && reading != b.stable) {
      b.stable = reading;
      Serial.printf("[btn] %s %s\n", teamName(b.team),
                    b.stable ? "pressed" : "released");
      if (g_handler) g_handler(b.team, b.stable);
    }
  }
}

bool buttonPressed(Team team) {
  for (auto &b : g_buttons) {
    if (b.team == team) return b.stable;
  }
  return false;
}

void buttonsSetHandler(ButtonEventHandler handler) { g_handler = handler; }
