#pragma once
//
// config.h — Compile-time configuration for the Airsoft Control Point System.
//
// Pin assignments, timing constants, and node-type selection live here.
// Secrets (WiFi credentials) do NOT live here — see secrets.h. Runtime config
// (node ID, WiFi credentials) is stored in NVS and can be re-provisioned over
// Serial without recompiling; the values below are only first-boot defaults.
//

// ---------------------------------------------------------------------------
// Node type selection
// ---------------------------------------------------------------------------
// Select via a build flag in platformio.ini (-D NODE_TYPE_CONTROLPOINT, etc.)
// so each environment compiles for one node type. A default is provided here
// so a bare `pio run` still builds.

#define NODE_TYPE_CONTROLPOINT 0
#define NODE_TYPE_FLAG         1
#define NODE_TYPE_REFEREE      2

#if !defined(NODE_TYPE)
  #if defined(NODE_TYPE_IS_CONTROLPOINT)
    #define NODE_TYPE NODE_TYPE_CONTROLPOINT
  #elif defined(NODE_TYPE_IS_FLAG)
    #define NODE_TYPE NODE_TYPE_FLAG
  #elif defined(NODE_TYPE_IS_REFEREE)
    #define NODE_TYPE NODE_TYPE_REFEREE
  #else
    #define NODE_TYPE NODE_TYPE_CONTROLPOINT  // default for bare builds
  #endif
#endif

#if NODE_TYPE == NODE_TYPE_CONTROLPOINT
  #define NODE_TYPE_STR     "controlpoint"
  #define DEFAULT_NODE_ID   "alpha"
#elif NODE_TYPE == NODE_TYPE_FLAG
  #define NODE_TYPE_STR     "flag"
  #define DEFAULT_NODE_ID   "flag1"
#elif NODE_TYPE == NODE_TYPE_REFEREE
  #define NODE_TYPE_STR     "referee"
  #define DEFAULT_NODE_ID   "ref1"
#else
  #error "Unknown NODE_TYPE"
#endif

// ---------------------------------------------------------------------------
// Network configuration
// ---------------------------------------------------------------------------
// Hostname prefix; full hostname becomes e.g. "airsoft-controlpoint-alpha".
// Used for mDNS/OTA discovery and DHCP hostname.
#define HOSTNAME_PREFIX "airsoft"

// WiFi reconnection backoff (milliseconds). Non-blocking: the main loop keeps
// running while we wait. Backoff doubles on each failed attempt up to the max
// so a downed AP doesn't spam connection attempts.
#define WIFI_RETRY_INTERVAL_MS      2000UL   // initial delay between attempts
#define WIFI_RETRY_INTERVAL_MAX_MS  30000UL  // cap on backoff
#define WIFI_CONNECT_TIMEOUT_MS     15000UL  // give up an attempt after this

// NVS namespace for persisted runtime config (node ID, WiFi credentials).
#define NVS_NAMESPACE "airsoft"

// ---------------------------------------------------------------------------
// Serial
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 115200

// ---------------------------------------------------------------------------
// Pin assignments — Control Point reference (see CLAUDE.md)
// ---------------------------------------------------------------------------
// Avoid GPIO 6-11 (flash). Be cautious with strapping pins 0, 2, 12, 15.
//
// PIN CONFLICT WARNING (e-paper bring-up, validated on a Waveshare 2.13"):
// GxEPD2 uses the ESP32 hardware VSPI bus — CLK=GPIO18, DIN/MOSI=GPIO23 — plus
// CS=5, DC=17, RST=16, BUSY=4. Note 18 and 23 below are reserved for the two
// TM1637 control-point displays, and CS=5 == PIN_LED_DATA. If a control point
// is to carry BOTH an e-paper display AND the TM1637s + LED strip, these must
// be re-assigned (move the e-paper to spare GPIOs, or use VSPI vs HSPI
// deliberately). Decide whether e-paper replaces the TM1637s before wiring.
#if NODE_TYPE == NODE_TYPE_CONTROLPOINT
  #define PIN_BTN_RED        25
  #define PIN_BTN_BLUE       26
  #define PIN_BTN_RESET      27
  #define PIN_DISP_RED_CLK   18
  #define PIN_DISP_RED_DIO   19
  #define PIN_DISP_BLUE_CLK  22
  #define PIN_DISP_BLUE_DIO  23
  #define PIN_LED_DATA        5
#elif NODE_TYPE == NODE_TYPE_FLAG
  #define PIN_BTN_RED        25
  #define PIN_BTN_BLUE       26
  #define PIN_LED_DATA        5
#elif NODE_TYPE == NODE_TYPE_REFEREE
  #define PIN_BTN_RED        25
  #define PIN_BTN_BLUE       26
  #define PIN_BTN_RESET      27
  #define PIN_LED_DATA        5
#endif
