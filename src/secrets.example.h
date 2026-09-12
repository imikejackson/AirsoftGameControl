#pragma once
//
// secrets.example.h — TEMPLATE. Copy this file to "secrets.h" and fill in your
// field WiFi credentials. secrets.h is gitignored so credentials never get
// committed.
//
//     cp src/secrets.example.h src/secrets.h   (or copy in your editor)
//
// These values are only used to SEED non-volatile storage (NVS) on first boot
// or when no credentials have been provisioned yet. Once a node is running you
// can change its credentials at runtime over Serial (see network.h) without
// recompiling — handy once nodes are sealed in enclosures.
//

#define DEFAULT_WIFI_SSID  "MKAirsoft Middletown"
#define DEFAULT_WIFI_PASS  "YOUR_FIELD_PASSWORD"

// Preset WiFi networks for the on-device LCD picker (first = default). On boot
// the LCD lists these and the Red/Blue buttons pick one; after a timeout it
// auto-connects to the last-used network. Each entry: { label, ssid, password }.
// The project's two networks: slot 0 = "Field" (MKAirsoft Middletown, RED
// button), slot 1 = "Ground Control" (home, BLUE button). More than one entry
// is required for the picker to appear at all: network.cpp falls back to a
// single "Default" preset otherwise, and the picker returns early when the
// count is 1. Fill in the real passwords in your local secrets.h (this template
// keeps them as placeholders so passwords never land in git).
#define WIFI_PRESETS { \
  { "Field",          DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASS }, \
  { "Ground Control", "Ground Control",  "YOUR_HOME_PASSWORD" }, \
}

// OTA update password. Empty string = no auth. Set a real password before
// deploying nodes in the field.
#define OTA_PASSWORD       ""
