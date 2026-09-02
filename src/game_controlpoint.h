#pragma once
//
// game_controlpoint.h — King-of-the-Hill control point logic.
//
// Local state is authoritative (CLAUDE.md): the buttons drive capture and the
// timers accrue here, independent of the network. A team captures by holding
// their button for CAPTURE_HOLD_MS; ownership then persists until the other
// team captures. Each team's CUMULATIVE hold time is banked across captures.
//
#include "types.h"

// Call once in setup() (after buttonsSetup, since it reads button state).
void gameSetup();

// Call every loop() iteration. Non-blocking: reads debounced buttons, advances
// the capture countdown, and transfers ownership when a capture completes.
void gameLoop();

Team gameOwner();

// Cumulative hold time for a team: banked time plus the live in-progress time
// if that team currently owns the point.
uint32_t gameCumulativeMs(Team team);

// Capture-in-progress state (for LED feedback during the 2.5s hold).
bool     gameCaptureInProgress();
Team     gameCapturingTeam();
uint32_t gameCaptureElapsedMs();

// Round running state. Default true (a standalone node just runs). When paused,
// timers freeze and captures are disabled; resuming doesn't count the paused
// gap. Driven by the retained airsoft/game/state and start/stop commands.
bool gameRunning();
void gameSetRunning(bool running);

// Rush: lock/unlock this box. A locked box ignores its team buttons (no capture)
// — used to disable the non-active bombs while another is active. The reset
// button and displays keep working.
void gameSetLocked(bool locked);
bool gameLocked();

// Game countdown clock, driven by the server via airsoft/game/state. The node
// displays the remaining time and freezes itself if it reaches zero (a local
// fallback so the round still ends if the server becomes unreachable).
void     gameSetCountdown(uint32_t remainingMs);
bool     gameHasClock();
uint32_t gameRemainingMs();

// Returns true exactly once after each game-state change (capture, reset, or
// running toggle), so the caller can publish on the edge. Consuming clears it.
bool gameConsumeStateChanged();

// Zero all timers and return to neutral. Triggered by a quick TAP of the reset
// button (if wired), an MQTT command, or the Serial "reset" command.
void gameReset();

// Returns true once when the reset button has been HELD long enough to open the
// local game menu (see RESET_HOLD_MS). Main polls this and shows the menu.
bool gameConsumeMenuRequest();

// Start a game locally on this node with no server involved: zero timers, go
// neutral, and run. durationMs > 0 runs a local countdown that ends the round at
// zero; durationMs == 0 is an endless round (no clock). This is the standalone
// fallback for when the broker/dashboard isn't available.
void gameStartLocal(uint32_t durationMs);
