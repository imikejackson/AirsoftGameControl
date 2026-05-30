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

// OTA update password. Empty string = no auth. Set a real password before
// deploying nodes in the field.
#define OTA_PASSWORD       ""
