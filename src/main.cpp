//
// main.cpp — Airsoft Control Point System firmware entry point.
//
// This is the shared base across all node types. It brings up the non-blocking
// WiFi module, an OLED live display, and the MQTT reporting/command channel;
// OTA, buttons, and LEDs layer on from here. The golden rule (CLAUDE.md):
// loop() must never block — no delay() — so buttons and the network stay
// responsive at all times.
//
#include <Arduino.h>
#include <ArduinoJson.h>

#include "config.h"
#include "network.h"
#include "mqtt.h"
#include "ota.h"
#include "buttons.h"
#include "statusled.h"
#include "game_controlpoint.h"
#include "oled.h"
#include "lcd.h"
#include "leds.h"

// Standalone mode (chosen in the boot mode picker): the node runs a local game
// and ignores the server's authoritative airsoft/game/state, so a locally
// started round isn't overridden. It still publishes its own state and accepts
// OTA. Default false = Connected (server-driven).
static bool g_standalone = false;

// Sleep + config-combo state.
static unsigned long g_lastActivityMs = 0;  // last button/game activity
static bool          g_asleep         = false;
static unsigned long g_bothHeldSince  = 0;   // when both buttons became held (0 = no)

// Publish the current game state as a retained JSON payload (small, hand-built
// to avoid pulling ArduinoJson into main). Called on each ownership change.
static void publishGameState() {
  String payload = String("{\"owner\":\"") + teamName(gameOwner()) +
                   "\",\"red_s\":" + String(gameCumulativeMs(TEAM_RED) / 1000) +
                   ",\"blue_s\":" + String(gameCumulativeMs(TEAM_BLUE) / 1000) +
                   ",\"running\":" + (gameRunning() ? "true" : "false") + "}";
  mqttPublishState(payload);
}

// Handle an inbound MQTT command. The retained airsoft/game/state carries the
// authoritative run state ({"running":true/false}); the command topics (this
// node's, or airsoft/game/command) carry actions: reset / start / stop.
static void onMqttCommand(const String &topic, const String &payload) {
  Serial.printf("[cmd] %s -> %s\n", topic.c_str(), payload.c_str());
  if (topic == "airsoft/game/state") {
    if (g_standalone) return;  // local game owns run state in standalone mode
    JsonDocument doc;
    if (deserializeJson(doc, payload)) return;  // bad JSON -> ignore
    long rem = doc["remaining_s"] | -1L;
    if (rem >= 0) gameSetCountdown((uint32_t)rem * 1000UL);
    gameSetRunning(doc["running"] | false);
    return;
  }
  if (payload.indexOf("reset") >= 0) gameReset();
  else if (payload.indexOf("start") >= 0) gameSetRunning(true);
  else if (payload.indexOf("stop") >= 0) gameSetRunning(false);
}

// Single owner of the Serial reader: read one line and dispatch it to each
// module's command handler so they never race for input.
static void pollSerialCommands() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  if (handleNetworkSerialCommand(line)) return;
  if (handleMqttSerialCommand(line)) return;
  if (line == "reset") {
    gameReset();
    return;
  }
  if (line == "score") {
    Serial.printf("[game] owner=%s red=%lus blue=%lus\n", teamName(gameOwner()),
                  (unsigned long)(gameCumulativeMs(TEAM_RED) / 1000),
                  (unsigned long)(gameCumulativeMs(TEAM_BLUE) / 1000));
    return;
  }
  Serial.println("[cfg] commands: wifi <ssid> <pass> | presets | preset <n> "
                 "| nodeid <id> | netstatus | mqtt <host> <port> | mqttstatus "
                 "| reset | score");
}

// Boot-time WiFi network picker on the LCD. Shows the preset networks; the Red
// and Blue buttons choose one. With exactly two presets, Red picks the first
// and Blue the second; with more, Red cycles the highlight and Blue confirms.
// If no button is pressed within WIFI_PICKER_TIMEOUT_MS the last-used network is
// kept (returns -1 = "no change"), so an unattended power-cycle just reconnects.
// Blocking is fine here: it runs in setup() before the radio/game come up.
// live = true when invoked at runtime (config combo): keep the network/MQTT/OTA
// serviced while the menu blocks. At boot pass false (radio not up yet).
static int runWifiPicker(bool live) {
  const int count = networkPresetCount();
  if (count <= 1) return -1;  // nothing to choose

  const int n = (count > 8) ? 8 : count;
  const char *labels[8];
  const char *ssids[8];
  for (int i = 0; i < n; i++) {
    labels[i] = networkPresetLabel(i);
    ssids[i]  = networkPresetSsid(i);
  }

  int sel = networkLastPresetIndex();
  if (sel >= n) sel = 0;

  // Prime edge detection so a button already held at power-on doesn't register.
  buttonsLoop();
  bool lastRed  = buttonPressed(TEAM_RED);
  bool lastBlue = buttonPressed(TEAM_BLUE);

  Serial.println("[wifi] picker: Red/Blue to choose network");
  const unsigned long start = millis();
  bool interacted = false;  // first press freezes the auto-select countdown
  int chosen = -1;
  for (;;) {
    if (live) { networkLoop(); otaLoop(); mqttLoop(); }
    buttonsLoop();
    const bool red  = buttonPressed(TEAM_RED);
    const bool blue = buttonPressed(TEAM_BLUE);
    const bool redEdge  = red  && !lastRed;
    const bool blueEdge = blue && !lastBlue;
    lastRed = red; lastBlue = blue;
    if (redEdge || blueEdge) interacted = true;

    if (n == 2) {
      if (redEdge)  { chosen = 0; break; }
      if (blueEdge) { chosen = 1; break; }
    } else {
      if (redEdge)  sel = (sel + 1) % n;
      if (blueEdge) { chosen = sel; break; }
    }

    int secs = -1;  // frozen (no countdown) once the user has interacted
    if (!interacted) {
      const unsigned long el = millis() - start;
      if (el >= WIFI_PICKER_TIMEOUT_MS) { chosen = -1; break; }
      secs = (int)((WIFI_PICKER_TIMEOUT_MS - el + 999) / 1000);
    }
    lcdShowWifiPicker(labels, ssids, n, sel, secs);
    delay(15);
  }
  Serial.printf("[wifi] picker result: %d\n", chosen);
  return chosen;
}

// Local game presets shown in the reset-hold menu. durationMs 0 = endless (no
// clock). All King-of-the-Hill today; new modes drop in as more rows once their
// game logic exists.
struct LocalGamePreset { const char *label; uint32_t durationMs; };
static const LocalGamePreset kLocalGames[] = {
    {"KotH  5 min", 5UL * 60 * 1000},
    {"KotH 10 min", 10UL * 60 * 1000},
    {"KotH 15 min", 15UL * 60 * 1000},
    {"KotH endless", 0},
};

// Local game menu: start a game standalone from the node, no server needed.
// Opened by holding the reset button (gameConsumeMenuRequest). Red cycles the
// highlight, Blue selects; a "Cancel" row and a timeout both back out. Blocks
// the main loop while open (an intentional operator action), but keeps the
// network/MQTT/OTA serviced so the connection doesn't drop.
static void runLocalGameMenu() {
  const int games = (int)(sizeof(kLocalGames) / sizeof(kLocalGames[0]));
  const int count = games + 1;  // + a trailing "Cancel" row
  const char *labels[8];
  const int n = (count > 8) ? 8 : count;
  for (int i = 0; i < games && i < 7; i++) labels[i] = kLocalGames[i].label;
  labels[games < 7 ? games : 7] = "Cancel";

  int sel = 0;
  buttonsLoop();
  bool lastRed  = buttonPressed(TEAM_RED);
  bool lastBlue = buttonPressed(TEAM_BLUE);

  Serial.println("[game] local game menu open");
  const unsigned long start = millis();
  for (;;) {
    networkLoop();  // keep the connection alive while we block here
    otaLoop();
    mqttLoop();

    buttonsLoop();
    const bool red  = buttonPressed(TEAM_RED);
    const bool blue = buttonPressed(TEAM_BLUE);
    const bool redEdge  = red  && !lastRed;
    const bool blueEdge = blue && !lastBlue;
    lastRed = red; lastBlue = blue;

    if (redEdge) sel = (sel + 1) % n;
    if (blueEdge) {
      if (sel < games) gameStartLocal(kLocalGames[sel].durationMs);
      else             Serial.println("[game] local menu cancelled");
      break;
    }
    if (millis() - start >= LOCAL_MENU_TIMEOUT_MS) {
      Serial.println("[game] local menu timed out");
      break;
    }
    const int secs =
        (int)((LOCAL_MENU_TIMEOUT_MS - (millis() - start) + 999) / 1000);
    lcdShowGameMenu("START GAME", labels, n, sel, secs);
    delay(15);
  }
  lcdForceRepaint();  // repaint the game screen over the menu on the next loop
}

// Boot mode picker (second menu, after the WiFi picker). Row 0 = Connected
// (server-driven); the rest are local standalone presets from kLocalGames.
// Red cycles, Blue selects; on timeout it defaults to Connected. Returns 0 for
// Connected or (preset index + 1) for a standalone game.
static int runModePicker(bool live) {
  const int games = (int)(sizeof(kLocalGames) / sizeof(kLocalGames[0]));
  const int count = games + 1;  // row 0 = Connected
  const int n = (count > 8) ? 8 : count;
  static String store[8];
  const char *labels[8];
  labels[0] = "Connected (server)";
  for (int i = 1; i < n; i++) {
    store[i] = String("Local: ") + kLocalGames[i - 1].label;
    labels[i] = store[i].c_str();
  }

  int sel = 0;  // default highlight = Connected
  buttonsLoop();
  bool lastRed  = buttonPressed(TEAM_RED);
  bool lastBlue = buttonPressed(TEAM_BLUE);

  Serial.println("[mode] picker: Connected vs local game");
  const unsigned long start = millis();
  bool interacted = false;  // first press freezes the auto-select countdown
  int chosen = 0;  // timeout -> Connected
  for (;;) {
    if (live) { networkLoop(); otaLoop(); mqttLoop(); }
    buttonsLoop();
    const bool red  = buttonPressed(TEAM_RED);
    const bool blue = buttonPressed(TEAM_BLUE);
    const bool redEdge  = red  && !lastRed;
    const bool blueEdge = blue && !lastBlue;
    lastRed = red; lastBlue = blue;
    if (redEdge || blueEdge) interacted = true;

    if (redEdge)  sel = (sel + 1) % n;
    if (blueEdge) { chosen = sel; break; }

    int secs = -1;  // frozen (no countdown) once the user has interacted
    if (!interacted) {
      const unsigned long el = millis() - start;
      if (el >= MODE_PICKER_TIMEOUT_MS) { chosen = 0; break; }
      secs = (int)((MODE_PICKER_TIMEOUT_MS - el + 999) / 1000);
    }
    lcdShowGameMenu("SELECT MODE", labels, n, sel, secs);
    delay(15);
  }
  Serial.printf("[mode] result: %d (%s)\n", chosen,
                chosen == 0 ? "connected" : "standalone");
  return chosen;
}

// Runtime config: the both-buttons combo re-runs the WiFi + mode menus without a
// reboot, so a sealed box (no reset/power button) can be reconfigured in place.
static void runRuntimeConfig() {
  Serial.println("[cfg] config combo -> WiFi + mode menus");
  const int wsel = runWifiPicker(/*live=*/true);
  if (wsel >= 0) { networkApplyPreset(wsel); networkReconnect(); }

  const int mode = runModePicker(/*live=*/true);
  if (mode == 0) {
    g_standalone = false;  // hand control back to the server
    Serial.println("[mode] now Connected");
  } else {
    g_standalone = true;
    gameStartLocal(kLocalGames[mode - 1].durationMs);
  }
  lcdForceRepaint();
}

// Both team buttons held COMBO_HOLD_MS opens the runtime config. Re-arms only
// after both buttons are released, so it can't immediately re-fire.
static void handleConfigCombo() {
  static bool armed = true;
  const bool red  = buttonPressed(TEAM_RED);
  const bool blue = buttonPressed(TEAM_BLUE);
  if (!(red && blue)) {
    g_bothHeldSince = 0;
    if (!red && !blue) armed = true;  // fully released -> ready to fire again
    return;
  }
  if (!armed) return;
  if (g_bothHeldSince == 0) {
    g_bothHeldSince = millis();
  } else if (millis() - g_bothHeldSince >= COMBO_HOLD_MS) {
    g_bothHeldSince = 0;
    armed = false;
    runRuntimeConfig();
    g_lastActivityMs = millis();
  }
}

// Blank the displays + run the rainbow chase after idle; wake on activity.
//
// "Awake" is driven by a REAL game being in progress, not the bare running
// flag: a Connected node defaults to running=true (and the dashboard may report
// a running game with no round actually under way), so keying off gameRunning()
// alone meant an idle connected node never slept. Instead we stay awake only
// while the point is held, a capture is happening, or a countdown is actively
// ticking. Otherwise — including a freshly booted Connected node that never
// starts a round — it sleeps after SLEEP_TIMEOUT_MS, same as standalone.
static void updateSleep() {
  const bool gameActive =
      gameOwner() != TEAM_NONE ||        // a team is holding the point
      gameCaptureInProgress() ||         // a capture is underway
      (gameRunning() && gameHasClock() && gameRemainingMs() > 0);  // clock ticking
  if (gameActive || buttonPressed(TEAM_RED) || buttonPressed(TEAM_BLUE))
    g_lastActivityMs = millis();
  const bool wantSleep = (millis() - g_lastActivityMs) >= SLEEP_TIMEOUT_MS;
  if (wantSleep && !g_asleep) {
    g_asleep = true;
    oledSleep();
    lcdBlank();
    Serial.println("[sleep] asleep -> rainbow");
  } else if (!wantSleep && g_asleep) {
    g_asleep = false;
    oledWake();
    lcdForceRepaint();
    Serial.println("[sleep] awake");
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(200);  // brief settle so the first logs aren't lost; only in setup()
  Serial.println();
  Serial.println("=== Airsoft Control Point System ===");
  Serial.printf("node type: %s\n", NODE_TYPE_STR);

  // Buttons + LCD first so the boot WiFi picker can use them. The picker has a
  // bounded timeout, so it can't keep a node offline (CLAUDE.md: WiFi/game must
  // keep working regardless of peripherals).
  buttonsSetup();
  lcdSetup();     // ST7789 control-point display (team color + big timers)

  // Menu 1 — WiFi network (Red/Blue); keep the last-used one on timeout.
  {
    const int sel = runWifiPicker(/*live=*/false);
    if (sel >= 0) networkApplyPreset(sel);
  }

  // Menu 2 — operating mode: Connected (server) or a local standalone game.
  // Only the team buttons are needed (no reset button required). Defaults to
  // Connected on timeout. Remember the chosen local duration to start below.
  int localDurationMs = -1;  // -1 = connected (no local game)
  {
    const int mode = runModePicker(/*live=*/false);  // 0 = connected; >0 = local
    if (mode > 0) {
      g_standalone    = true;
      localDurationMs = (int)kLocalGames[mode - 1].durationMs;
    }
  }

  networkSetup();  // connect with the (possibly just-picked) credentials
  mqttSetup();
  mqttSetCommandHandler(onMqttCommand);
  otaSetup();      // arms once WiFi is up, inside otaLoop()

  statusLedSetup();
  gameSetup();     // after buttonsSetup: the game reads debounced button state

  oledSetup();     // live display; the game still runs headless if absent
  ledsSetup();     // WS2812B ownership strip on GPIO 5 (external-powered)

  // Standalone: start the chosen local game now that the game module is up.
  if (g_standalone) gameStartLocal((uint32_t)localDurationMs);

  g_lastActivityMs = millis();  // don't sleep immediately after boot
}

// Drive the onboard RGB from the GAME state: solid owner color when held, the
// capturing team's color BLINKING during the 2.5 s capture hold, off when
// neutral. Only writes the pixel when the color actually changes. (Bring-up
// indicator; real ownership color will come from the WS2812B strip module.)
static void updateStatusLed() {
  uint8_t r = 0, g = 0, b = 0;
  if (gameCaptureInProgress()) {
    const bool on = (millis() / 200) % 2;  // ~2.5 Hz blink while capturing
    if (on) (gameCapturingTeam() == TEAM_RED ? r : b) = 60;
  } else {
    const Team owner = gameOwner();
    if (owner == TEAM_RED) r = 60;
    else if (owner == TEAM_BLUE) b = 60;
  }
  static uint8_t lr = 1, lg = 1, lb = 1;  // impossible init -> first write
  if (r != lr || g != lg || b != lb) {
    lr = r; lg = g; lb = b;
    statusLedSetColor(r, g, b);
  }
}

void loop() {
  networkLoop();        // drive WiFi connect/reconnect state machine
  otaLoop();            // service OTA listener (arms once WiFi is up)
  mqttLoop();           // drive MQTT connect/reconnect + service messages
  pollSerialCommands(); // runtime provisioning (wifi/nodeid/mqtt/...)

  buttonsLoop();       // debounce + button edge events
  handleConfigCombo(); // both buttons held COMBO_HOLD_MS -> runtime config menus

  gameLoop();          // capture countdown, ownership transfer, cumulative timers

  // Reset button held -> open the local game menu (only if a reset button is
  // wired; the config combo above is the button-only equivalent).
  if (gameConsumeMenuRequest()) runLocalGameMenu();

  // On a game-state change (capture, reset, or start/stop), report over MQTT.
  if (gameConsumeStateChanged()) publishGameState();

  updateSleep();  // blank displays + rainbow after idle; wake on activity

  if (g_asleep) {
    ledsRainbow();  // sleep animation; displays stay blanked
  } else {
    updateStatusLed();  // onboard RGB reflects ownership/capture

    // WS2812B ownership strip: solid team color when held, capturing-team
    // progress-fill during the hold, dim idle glow when neutral.
    ledsShow(gameOwner(), gameCaptureInProgress(), gameCapturingTeam(),
             gameCaptureElapsedMs(), gameRunning());

    // Live game displays on the OLED (I2C) and the ST7789 LCD (SPI). Each
    // throttles itself and no-ops if not connected.
    oledShowGame(nodeId(), gameOwner(), gameCumulativeMs(TEAM_RED),
                 gameCumulativeMs(TEAM_BLUE), gameCaptureInProgress(),
                 gameCapturingTeam(), gameCaptureElapsedMs());
    const int32_t remainingS =
        gameHasClock() ? (int32_t)(gameRemainingMs() / 1000) : -1;
    lcdShowGame(nodeId(), gameOwner(), gameCumulativeMs(TEAM_RED),
                gameCumulativeMs(TEAM_BLUE), gameCaptureInProgress(),
                gameCapturingTeam(), gameCaptureElapsedMs(), wifiConnected(),
                wifiIpString(), gameRunning(), remainingS);
  }

  // Lightweight heartbeat to Serial so we can confirm the loop is alive and
  // watch connection state without blocking. Non-blocking millis() timer.
  static unsigned long lastBeat = 0;
  if (millis() - lastBeat >= 5000) {
    lastBeat = millis();
    Serial.printf("[hb] wifi: %s | mqtt: %s\n",
                  wifiStatusString().c_str(), mqttStatusString().c_str());
  }
}
