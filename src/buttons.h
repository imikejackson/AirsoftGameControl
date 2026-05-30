#pragma once
//
// buttons.h — Debounced team buttons (red/blue), active-low on INPUT_PULLUP.
//
// Each button is a plain 2-terminal momentary switch wired GPIO -> button -> GND
// (no external resistor; the internal pull-up holds the pin HIGH until pressed).
// This module debounces them and exposes both the current state and press/
// release edge events. Game logic (capture hold, ownership) layers on top.
//
#include "types.h"

// Fired on a debounced edge: pressed=true on press, false on release.
typedef void (*ButtonEventHandler)(Team team, bool pressed);

// Call once in setup(). Configures the button GPIOs as INPUT_PULLUP.
void buttonsSetup();

// Call every loop() iteration. Non-blocking; updates debounced state and fires
// edge events through the registered handler.
void buttonsLoop();

// Current debounced state for a team's button (true = currently held).
bool buttonPressed(Team team);

// Register the edge-event handler (one handler; last registration wins).
void buttonsSetHandler(ButtonEventHandler handler);
