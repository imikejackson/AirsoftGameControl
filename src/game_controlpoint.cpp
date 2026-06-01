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
bool          g_stateChanged  = false;     // owner/timers/running changed -> republish
bool          g_running       = true;      // round active? paused freezes everything

// Game countdown clock (server-driven via airsoft/game/state).
bool          g_hasClock        = false;
uint32_t      g_setRemainingMs  = 0;       // remaining as of the last clock update
unsigned long g_clockReceiptMs  = 0;       // millis() of that update

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

  // Local game-over fallback: if the countdown has run out, freeze. The server
  // normally ends the round, but this keeps it correct if the server drops.
  if (g_running && g_hasClock &&
      (uint32_t)(now - g_clockReceiptMs) >= g_setRemainingMs) {
    Serial.println("[game] countdown reached 0 -> game over");
    gameSetRunning(false);
  }

  // Paused / over: freeze the game — no captures, no accrual (reset still works).
  if (!g_running) {
    g_capturing = TEAM_NONE;
    return;
  }

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
    g_stateChanged = true;
    Serial.printf("[game] captured by %s\n", teamName(g_owner));
  }
}

Team gameOwner() { return g_owner; }

uint32_t gameCumulativeMs(Team team) {
  uint32_t ms = g_cumMs[team];
  if (g_owner == team && g_running) ms += (uint32_t)(millis() - g_ownerStart);
  return ms;
}

bool gameRunning() { return g_running; }

void gameSetCountdown(uint32_t remainingMs) {
  g_setRemainingMs = remainingMs;
  g_clockReceiptMs = millis();
  g_hasClock = true;
}

bool gameHasClock() { return g_hasClock; }

uint32_t gameRemainingMs() {
  if (!g_hasClock) return 0;
  if (!g_running) return g_setRemainingMs;  // frozen while paused / over
  const uint32_t elapsed = (uint32_t)(millis() - g_clockReceiptMs);
  return (elapsed < g_setRemainingMs) ? (g_setRemainingMs - elapsed) : 0;
}

void gameSetRunning(bool running) {
  if (running == g_running) return;
  const unsigned long now = millis();
  if (running) {
    g_ownerStart = now;       // resume: don't count the paused gap
  } else {
    bankOwnerTime(now);       // pause: bank the live accrual, then freeze
    g_capturing = TEAM_NONE;  // abort any in-progress capture
  }
  g_running = running;
  g_stateChanged = true;
  Serial.printf("[game] %s\n", running ? "START (running)" : "STOP (paused)");
}

bool gameCaptureInProgress() { return g_capturing != TEAM_NONE; }
Team gameCapturingTeam()     { return g_capturing; }

uint32_t gameCaptureElapsedMs() {
  return (g_capturing == TEAM_NONE) ? 0 : (uint32_t)(millis() - g_captureStart);
}

bool gameConsumeStateChanged() {
  const bool changed = g_stateChanged;
  g_stateChanged = false;
  return changed;
}

void gameReset() {
  g_owner        = TEAM_NONE;
  g_cumMs[TEAM_NONE] = g_cumMs[TEAM_RED] = g_cumMs[TEAM_BLUE] = 0;
  g_ownerStart   = millis();
  g_capturing    = TEAM_NONE;
  g_stateChanged = true;
  Serial.println("[game] reset -> neutral, timers zeroed");
}
