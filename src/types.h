#pragma once
//
// types.h — Small shared types used across modules (buttons, LEDs, game logic,
// MQTT state). Kept dependency-free so any module can include it.
//
#include <Arduino.h>

// Which team owns/triggered something. TEAM_NONE = neutral/unheld.
enum Team { TEAM_NONE = 0, TEAM_RED, TEAM_BLUE };

inline const char *teamName(Team t) {
  switch (t) {
    case TEAM_RED:  return "red";
    case TEAM_BLUE: return "blue";
    default:        return "none";
  }
}
