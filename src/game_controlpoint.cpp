//
// game_controlpoint.cpp — King-of-the-Hill control point logic.
//
#include "game_controlpoint.h"
#include "config.h"
#include "buttons.h"

#include <Arduino.h>

namespace {

Team          g_owner      = TEAM_NONE;
uint32_t      g_cumMs[3]   = {0, 0, 0};  // indexed by Team (NONE/RED/BLUE)
unsigned long g_ownerStart = 0;          // millis() when current owner took it

Team          g_capturing    = TEAM_NONE;  // team mid-capture, NONE if none
unsigned long g_captureStart  = 0;
bool          g_ownerChanged  = false;

#ifdef PIN_BTN_RESET
bool          g_resetStable   = false;
bool          g_resetReading  = false;
unsigned long g_resetChangeMs = 0;
#endif

// Fold the current owner's elapsed time into its banked total.
void bankOwnerTime(unsigned long now) {
  if (g_owner != TEAM_NONE) {
    g_cumMs[g_owner] += (uint32_t)(now - g_ownerStart);
    g_ownerStart = now;
  }
}

// Which non-owner team is currently attempting a capture. The owner's own
// button is ignored; if both eligible buttons are held it's a conflict and
// nobody captures.
Team attemptingTeam() {
  bool red  = buttonPressed(TEAM_RED);
  bool blue = buttonPressed(TEAM_BLUE);
  if (g_owner == TEAM_RED)  red  = false;  // own-team button does nothing
  if (g_owner == TEAM_BLUE) blue = false;
  if (red && blue) return TEAM_NONE;       // conflict
  if (red)  return TEAM_RED;
  if (blue) return TEAM_BLUE;
  return TEAM_NONE;
}

}  // namespace

void gameSetup() {
#ifdef PIN_BTN_RESET
  pinMode(PIN_BTN_RESET, INPUT_PULLUP);
  g_resetReading = g_resetStable = (digitalRead(PIN_BTN_RESET) == LOW);
  g_resetChangeMs = millis();
#endif
  gameReset();
}

void gameLoop() {
  const unsigned long now = millis();

#ifdef PIN_BTN_RESET
  // Debounce the optional physical reset button (safe if unwired: reads HIGH).
  const bool rd = (digitalRead(PIN_BTN_RESET) == LOW);
  if (rd != g_resetReading) {
    g_resetReading  = rd;
    g_resetChangeMs = now;
  }
  if ((now - g_resetChangeMs) >= BUTTON_DEBOUNCE_MS && rd != g_resetStable) {
    g_resetStable = rd;
    if (rd) {
      Serial.println("[game] reset button pressed");
      gameReset();
    }
  }
#endif

  const Team attempt = attemptingTeam();
  if (attempt == TEAM_NONE) {
    g_capturing = TEAM_NONE;  // released or conflict -> capture aborts
  } else if (attempt != g_capturing) {
    g_capturing   = attempt;  // a new capture attempt starts the countdown
    g_captureStart = now;
  } else if ((now - g_captureStart) >= CAPTURE_HOLD_MS) {
    // Held long enough — transfer ownership, banking the old owner's time.
    bankOwnerTime(now);
    g_owner        = attempt;
    g_ownerStart   = now;
    g_capturing    = TEAM_NONE;
    g_ownerChanged = true;
    Serial.printf("[game] captured by %s\n", teamName(g_owner));
  }
}

Team gameOwner() { return g_owner; }

uint32_t gameCumulativeMs(Team team) {
  uint32_t ms = g_cumMs[team];
  if (g_owner == team) ms += (uint32_t)(millis() - g_ownerStart);
  return ms;
}

bool gameCaptureInProgress() { return g_capturing != TEAM_NONE; }
Team gameCapturingTeam()     { return g_capturing; }

uint32_t gameCaptureElapsedMs() {
  return (g_capturing == TEAM_NONE) ? 0 : (uint32_t)(millis() - g_captureStart);
}

bool gameConsumeOwnershipChanged() {
  const bool changed = g_ownerChanged;
  g_ownerChanged = false;
  return changed;
}

void gameReset() {
  g_owner        = TEAM_NONE;
  g_cumMs[TEAM_NONE] = g_cumMs[TEAM_RED] = g_cumMs[TEAM_BLUE] = 0;
  g_ownerStart   = millis();
  g_capturing    = TEAM_NONE;
  g_ownerChanged = true;
  Serial.println("[game] reset -> neutral, timers zeroed");
}
