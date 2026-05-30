#pragma once
//
// epaper.h — Status display on the Waveshare 2.13" e-paper (GDE0213B1 / IL3895).
//
// Shows the node's identity and network status: control-point name, node type,
// SSID, and IP address. This is a low-rate STATUS display, not a game surface.
//
// IMPORTANT: a full e-paper refresh on this old panel blocks for ~3.9 s. That
// violates the non-blocking loop() rule, so we only ever refresh when the shown
// information actually CHANGES (connect, reconnect, IP change) — not every loop.
// Call epaperUpdateStatus() each loop; it cheaply no-ops until something differs.
//
#include <Arduino.h>
#include "types.h"

// Initialize the panel and draw an initial "booting" screen. Call once in
// setup(), after networkSetup() (so we can show whatever state exists).
void epaperSetup();

// Call every loop() iteration. Redraws ONLY when the rendered content changes,
// so it is free to call continuously. The redraw itself is blocking (~4 s) but
// happens rarely. Pass current values from the network module.
void epaperUpdateStatus(const String &nodeName, const char *nodeType,
                        bool connected, const String &ssid, const String &ip);

// Control-point game screen: ownership + cumulative MM:SS per team, plus a
// small network footer. Redraws ONLY when the content changes (same slow-
// refresh caveat as above), so the CALLER must throttle how often it calls
// this — see main: on ownership change, else slowly and only when idle.
void epaperUpdateGame(const String &nodeName, Team owner, uint32_t redSecs,
                      uint32_t blueSecs, bool connected, const String &ip);
