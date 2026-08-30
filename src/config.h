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
// Firmware version
// ---------------------------------------------------------------------------
// Simple monotonic integer. Increment by 1 on EVERY firmware change. Shown on
// the e-paper so you can confirm which build a node is running — especially
// useful for spotting whether an OTA push actually took.
#define FIRMWARE_VERSION 32

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

// On-boot WiFi picker: the LCD shows the preset networks (from secrets.h) and
// the Red/Blue buttons select one. If no button is pressed within this window,
// the node auto-connects to the last-used network (so an unattended power-cycle
// in the field just reconnects with no interaction). Set to 0 to disable.
// Auto-select countdown for the boot menus. The countdown FREEZES on the first
// button press (once you interact, it waits for an explicit choice).
#define WIFI_PICKER_TIMEOUT_MS 15000UL

// Second boot menu (after the WiFi picker): choose Connected (server-driven) vs
// a local standalone game. Red cycles, Blue selects; on timeout it defaults to
// Connected (the safe unattended choice — the node just joins the server).
#define MODE_PICKER_TIMEOUT_MS 15000UL

// Re-enter the config menus (WiFi + mode) at runtime WITHOUT rebooting: hold
// BOTH team buttons this long. Lets you reconfigure a sealed box (no reset/power
// button wired) in the field.
#define COMBO_HOLD_MS 10000UL

// Sleep: with no game running and no button activity for this long, blank the
// displays and run a rainbow LED chase. Any button press (or a game starting)
// wakes it. Lower this while testing so you don't wait 10 minutes.
#define SLEEP_TIMEOUT_MS 600000UL  // 10 minutes

// ---------------------------------------------------------------------------
// MQTT configuration
// ---------------------------------------------------------------------------
// Broker is the central Raspberry Pi. Default is an mDNS name; override at
// runtime over Serial ("mqtt <host> <port>") — e.g. point at a numeric IP if
// .local resolution isn't available, or a public test broker during bring-up.
#define DEFAULT_MQTT_HOST "airsoft-pi.local"
#define DEFAULT_MQTT_PORT 1883

#define MQTT_HEARTBEAT_INTERVAL_MS  12000UL  // alive signal cadence (10-15s)
#define MQTT_RETRY_INTERVAL_MS       3000UL  // initial reconnect backoff
#define MQTT_RETRY_INTERVAL_MAX_MS  30000UL  // cap on reconnect backoff
#define MQTT_BUFFER_SIZE              512     // PubSubClient packet buffer (bytes)

// ---------------------------------------------------------------------------
// Serial
// ---------------------------------------------------------------------------
#define SERIAL_BAUD 115200

// ---------------------------------------------------------------------------
// Buttons / input
// ---------------------------------------------------------------------------
// Debounce window — a button must read stable this long before we accept the
// new state (CLAUDE.md: 50ms minimum).
#define BUTTON_DEBOUNCE_MS 50UL

// ---------------------------------------------------------------------------
// Game logic
// ---------------------------------------------------------------------------
// A team must hold their button continuously this long to capture the point.
// Kept short (0.5s) for snappy, near-instant flips; still long enough to reject
// an accidental brush of the button.
#define CAPTURE_HOLD_MS 500UL

// Reset button: a quick TAP zeros timers (neutral); a long HOLD opens the local
// game menu on the LCD (start a game standalone, no server needed). This is the
// threshold that separates a tap from a hold.
#define RESET_HOLD_MS 1500UL

// Local game menu: auto-closes (cancels) after this long with no button input,
// so it can't get stuck open on a deployed node.
#define LOCAL_MENU_TIMEOUT_MS 15000UL

// Grace window: a momentary loss of the button during a capture (contact bounce
// on cheap buttons, a loose terminal) is tolerated for this long before the
// capture aborts. This keeps a hold from restarting on every flicker, so the
// effective capture time lands at ~CAPTURE_HOLD_MS instead of dragging out over
// several retries. The countdown pauses (does not reset) during the gap.
#define CAPTURE_GRACE_MS 200UL

// ---------------------------------------------------------------------------
// Onboard status RGB LED
// ---------------------------------------------------------------------------
// Single WS2812/NeoPixel on the dev board, GPIO 2. Driven via the ESP32 core's
// neopixelWrite() — no library needed. GPIO 2 is a strapping pin, but we only
// drive it after boot (the data line idles beforehand), so it's safe here.
// NOTE: this is the dev-board status pixel, distinct from PIN_LED_DATA (the
// WS2812B ownership strip on GPIO 5) added with the LED module later.
#define PIN_STATUS_RGB 2

// ---------------------------------------------------------------------------
// OLED display (the live information display)
// ---------------------------------------------------------------------------
// SSD1306 128x64 I2C (e.g. UCTRONICS 0.96"). Fast (~30ms) refresh, so it shows
// LIVE-ticking timers. The cheap "yellow/blue" panels are monochrome with a
// FIXED top ~16px yellow / bottom blue split (not controllable) — team color
// comes from the LEDs (and later the ST7789 LCD). Probed on the I2C bus at
// boot; if absent the game still runs headless. SCL lands on GPIO 22, the old
// (now-dropped) TM1637 blue-CLK reservation.
#define PIN_OLED_SDA    21
#define PIN_OLED_SCL    22
#define OLED_I2C_ADDR   0x3C
#define OLED_WIDTH      128
#define OLED_HEIGHT     64
#define OLED_REFRESH_MS 200UL  // ~5 Hz live update; cheap, non-blocking

// ---------------------------------------------------------------------------
// ST7789 LCD (2" 240x320 IPS, Waveshare ST7789V) — control-point display
// ---------------------------------------------------------------------------
// Driven by TFT_eSPI, whose pins/driver are configured via build_flags in
// platformio.ini (SCK=18, MOSI=23, CS=4, DC=17, RST=16; BL tied to 3.3V).
// Landscape, team-colored background + a large 7-segment timer. No presence
// probe (SPI has no ACK); if unwired the writes simply go nowhere.
#define LCD_REFRESH_MS 200UL

// ---------------------------------------------------------------------------
// WS2812B ownership LED strip
// ---------------------------------------------------------------------------
// Data on PIN_LED_DATA (GPIO 5), driven by FastLED. Power is injected into the
// strip from a separate 5V supply (share ground with the ESP32). Shows the
// owning team's color, a progress-fill during a capture, and a dim idle glow
// when neutral. SET NUM_LEDS to your strip's actual LED count.
#define NUM_LEDS       300
#define LED_BRIGHTNESS 120    // global brightness 0-255

// Owner "chase" animation: while a team holds the point, a bright comet of the
// team color sweeps along a dim team-color base. Pure eye-candy — CPU cost is
// negligible (per-frame math is a few microseconds; FastLED.show() cost depends
// only on LED count, and we already show() every frame). Tunables:
#define CHASE_STEP_MS     22   // ms the comet advances one pixel (lower = faster)
#define CHASE_TAIL        12   // comet length in pixels (bright head + fading tail)
#define CHASE_BASE_SCALE  55   // brightness of the static team-color base (0-255)
#define CHASE_SPACING     30   // approx pixels between comets; a train of
                               // NUM_LEDS/CHASE_SPACING comets is tiled evenly
                               // around the strip. Raise for fewer comets, set
                               // >= NUM_LEDS for a single comet.

// Power budget for the strip's 5V supply. FastLED auto-dims so total draw never
// exceeds this (see leds.cpp). 4500mA suits a 5V/5A supply shared with the
// ESP32 (~500mA headroom). Bump ONLY if you fit a larger 5V supply.
#define LED_MAX_MILLIAMPS 4500

// ---------------------------------------------------------------------------
// Pin assignments — Control Point reference (see CLAUDE.md)
// ---------------------------------------------------------------------------
// Avoid GPIO 6-11 (flash). Be cautious with strapping pins 0, 2, 12, 15.
//
// DISPLAY PLAN: the e-paper has been retired. The live display is the SSD1306
// OLED on I2C (SDA=21, SCL=22). A 2" ST7789 LCD (SPI: SCK/MOSI/CS/DC/RST/BL)
// will become the production control-point display and supersedes the TM1637
// 7-segment timers — so the PIN_DISP_* defines below are legacy reference only
// (unused; the LCD's SPI pins will be assigned when that module lands). Note
// the OLED's SCL (22) reuses the old TM1637 blue-CLK pin, which is fine now
// that the TM1637s are dropped.
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
