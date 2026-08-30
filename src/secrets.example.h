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

#define DEFAULT_WIFI_SSID  "YOUR_FIELD_SSID"
#define DEFAULT_WIFI_PASS  "YOUR_WIFI_PASSWORD"

// Preset WiFi networks for the on-device LCD picker (first = default). On boot
// the LCD lists these and the Red/Blue buttons pick one; after a timeout it
// auto-connects to the last-used network. Each entry: { label, ssid, password }.
// If you omit this, the firmware falls back to a single preset built from
// DEFAULT_WIFI_SSID/PASS above.
#define WIFI_PRESETS { \
  { "Home",  DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASS }, \
  { "Field", "FIELD_AP_SSID",   "FIELD_AP_PASSWORD" }, \
}

// OTA update password. Empty string = no auth. Set a real password before
// deploying nodes in the field.
#define OTA_PASSWORD       ""
