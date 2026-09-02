//
// lcd.cpp — ST7789 control-point display via TFT_eSPI (landscape 320x240).
//
// Two-row scoreboard layout: a RED row (top 100px) and a BLUE row (middle
// 100px), each showing that team's cumulative time in the clean Font 6 clock
// font, on the team's color. The OWNING team's row is full brightness; the
// other (and both, when neutral) is dimmed — so the bright row is the at-a-
// glance "who's holding it" cue. A 40px status strip across the bottom shows
// the node name, IP, version, and the capture progress bar.
//
// Flicker-free: a row's background repaints only when its brightness changes;
// the time text overwrites in place each second; the status strip and bar
// repaint only on change.
//
#include "lcd.h"
#include "config.h"

#include <TFT_eSPI.h>

namespace {

TFT_eSPI tft = TFT_eSPI();

unsigned long g_lastDraw   = 0;
int           g_redBright  = -1;  // -1 forces first paint
int           g_blueBright = -1;
String        g_lastRedT   = "";
String        g_lastBlueT  = "";
String        g_lastStatus = "";
int           g_lastBarPct = -1;
int           g_pickerSel  = -999;  // WiFi picker: last-rendered selection
int           g_pickerSecs = -999;  // WiFi picker: last-rendered countdown secs
int           g_menuSel    = -999;  // game menu: last-rendered selection
int           g_menuSecs   = -999;  // game menu: last-rendered countdown secs

const int ROW_H    = 100;
const int RED_Y    = 0;
const int BLUE_Y   = 100;
const int STATUS_Y = 200;
const int TIME_FONT = 6;
const int TIME_SIZE = 2;

uint16_t teamColor(Team t) {
  return (t == TEAM_RED) ? TFT_RED : (t == TEAM_BLUE) ? TFT_BLUE : TFT_DARKGREY;
}

String fmtTime(uint32_t ms) {  // MM:SS, fixed width
  const uint32_t s = ms / 1000;
  char b[16];
  snprintf(b, sizeof(b), "%02lu:%02lu", (unsigned long)(s / 60), (unsigned long)(s % 60));
  return String(b);
}

// Paint a team row's background + small label (only on a brightness change).
void paintRow(int y, const char *label, uint16_t bg) {
  tft.fillRect(0, y, tft.width(), ROW_H, bg);
  tft.setTextColor(TFT_WHITE, bg);
  tft.setTextDatum(TL_DATUM);
  tft.drawString(label, 6, y + 6, 2);
}

// Draw/refresh a row's time, centered, overwriting in place.
void paintTime(int y, const String &t, uint16_t bg) {
  tft.setTextColor(TFT_WHITE, bg);
  tft.setTextDatum(MC_DATUM);
  tft.setTextSize(TIME_SIZE);
  tft.drawString(t, tft.width() / 2, y + ROW_H / 2 + 6, TIME_FONT);
  tft.setTextSize(1);
}

}  // namespace

void lcdSetup() {
  tft.init();
  tft.setRotation(1);  // landscape 320x240
  tft.fillScreen(TFT_BLACK);
  g_redBright = g_blueBright = -1;
  g_lastRedT = g_lastBlueT = g_lastStatus = "";
  g_lastBarPct = -1;
  Serial.println("[lcd] TFT_eSPI ST7789 initialized (landscape 320x240)");
}

void lcdShowGame(const String &nodeName, Team owner, uint32_t redMs,
                 uint32_t blueMs, bool capturing, Team capturingTeam,
                 uint32_t captureElapsedMs, bool connected, const String &ip,
                 bool running, int32_t remainingS) {
  if ((millis() - g_lastDraw) < LCD_REFRESH_MS) return;
  g_lastDraw = millis();

  const int W = tft.width();

  // Owning team's row is full color; the other (and both, when neutral) dimmed.
  const int redBright  = (owner == TEAM_RED) ? 1 : 0;
  const int blueBright = (owner == TEAM_BLUE) ? 1 : 0;
  const uint16_t redBg  = redBright  ? TFT_RED  : tft.color565(80, 0, 0);
  const uint16_t blueBg = blueBright ? TFT_BLUE : tft.color565(0, 0, 95);

  // RED row.
  if (redBright != g_redBright) {
    g_redBright = redBright;
    paintRow(RED_Y, "RED", redBg);
    g_lastRedT = "";
  }
  String rt = fmtTime(redMs);
  if (rt != g_lastRedT) {
    paintTime(RED_Y, rt, redBg);
    g_lastRedT = rt;
  }

  // BLUE row.
  if (blueBright != g_blueBright) {
    g_blueBright = blueBright;
    paintRow(BLUE_Y, "BLUE", blueBg);
    g_lastBlueT = "";
  }
  String bt = fmtTime(blueMs);
  if (bt != g_lastBlueT) {
    paintTime(BLUE_Y, bt, blueBg);
    g_lastBlueT = bt;
  }

  // Status strip (two lines): name | game countdown | version  on line 1;
  // IP, or a yellow PAUSED / red TIME! indicator, on line 2.
  String name = nodeName;
  name.toUpperCase();
  char cdBuf[8];
  if (remainingS < 0) {
    strncpy(cdBuf, "--:--", sizeof(cdBuf));
  } else {
    snprintf(cdBuf, sizeof(cdBuf), "%ld:%02ld", (long)(remainingS / 60),
             (long)(remainingS % 60));
  }
  const bool over = (!running && remainingS == 0);
  String line2 = running ? (connected ? ip : String("no wifi"))
                         : (over ? String("** TIME! **") : String("** PAUSED **"));
  String key = name + "|" + cdBuf + "|" + line2;
  if (key != g_lastStatus) {
    tft.fillRect(0, STATUS_Y, W, 40, TFT_BLACK);
    // Line 1: box name on the left, countdown on the right (no center overlap,
    // so long names like "PINK HALLWAY" have room).
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setTextDatum(TL_DATUM);
    tft.drawString(name, 6, STATUS_Y + 2, 2);
    uint16_t cdCol = over ? TFT_RED
                          : (!running ? TFT_YELLOW
                                      : (remainingS >= 0 && remainingS <= 10 ? TFT_RED : TFT_WHITE));
    tft.setTextColor(cdCol, TFT_BLACK);
    tft.setTextDatum(TR_DATUM);
    tft.drawString(cdBuf, W - 6, STATUS_Y + 2, 2);
    // Line 2: version + IP / status indicator.
    tft.setTextColor(running ? TFT_DARKGREY : (over ? TFT_RED : TFT_YELLOW), TFT_BLACK);
    tft.setTextDatum(TL_DATUM);
    tft.drawString("v" + String(FIRMWARE_VERSION) + "  " + line2, 6, STATUS_Y + 22, 1);
    g_lastStatus = key;
    g_lastBarPct = -1;  // force bar repaint
  }

  // Capture progress bar (capturing team's color).
  uint32_t pctU = capturing ? captureElapsedMs * 100 / CAPTURE_HOLD_MS : 0;
  if (pctU > 100) pctU = 100;
  const int pct = (int)pctU;
  if (pct != g_lastBarPct) {
    g_lastBarPct = pct;
    const int y = STATUS_Y + 33, h = 5, bw = W - 12;
    tft.fillRect(6, y, bw, h, TFT_BLACK);
    if (pct > 0) {
      tft.drawRect(6, y, bw, h, TFT_WHITE);
      tft.fillRect(6, y, bw * pct / 100, h, teamColor(capturingTeam));
    }
  }

  // A game screen was drawn; make the next picker/menu call full-repaint.
  g_pickerSel = -999;
  g_menuSel   = -999;
  g_menuSecs  = -999;
}

void lcdShowWifiPicker(const char *const labels[], const char *const ssids[],
                       int count, int sel, int secondsLeft) {
  const int W = tft.width();
  const int H = tft.height();

  // Full layout only when the selection changes (or first call); the countdown
  // updates in place so the screen doesn't flicker.
  if (sel != g_pickerSel) {
    g_pickerSel  = sel;
    g_pickerSecs = -999;  // force the countdown line to repaint
    tft.fillScreen(TFT_BLACK);

    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setTextDatum(TC_DATUM);
    tft.drawString("SELECT WiFi", W / 2, 8, 4);

    const int top = 44, footer = 28, gap = 8;
    const int n = (count < 1) ? 1 : count;
    int rowH = (H - top - footer - (n - 1) * gap) / n;
    if (rowH > 72) rowH = 72;

    for (int i = 0; i < count; i++) {
      const int y = top + i * (rowH + gap);
      const bool hi = (i == sel);
      // First two rows map to the Red / Blue buttons; the rest are grey.
      const uint16_t full = (i == 0) ? TFT_RED : (i == 1) ? TFT_BLUE : TFT_DARKGREY;
      const uint16_t dim  = (i == 0) ? tft.color565(80, 0, 0)
                          : (i == 1) ? tft.color565(0, 0, 90)
                                     : tft.color565(45, 45, 45);
      const uint16_t bg = hi ? full : dim;
      tft.fillRoundRect(10, y, W - 20, rowH, 8, bg);
      if (hi) tft.drawRoundRect(10, y, W - 20, rowH, 8, TFT_WHITE);

      const char *chip = (i == 0) ? "RED" : (i == 1) ? "BLUE" : "";
      tft.setTextColor(TFT_WHITE, bg);
      if (chip[0]) {
        tft.setTextDatum(ML_DATUM);
        tft.drawString(chip, 20, y + rowH / 2, 2);
      }
      tft.setTextDatum(TL_DATUM);
      tft.drawString(labels[i], 95, y + 6, 4);          // friendly name
      tft.drawString(ssids[i], 95, y + rowH - 20, 2);   // actual SSID
    }
  }

  if (secondsLeft != g_pickerSecs) {
    g_pickerSecs = secondsLeft;
    const int fy = H - 24;
    tft.fillRect(0, fy, W, 24, TFT_BLACK);
    tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    tft.setTextDatum(TC_DATUM);
    char buf[64];
    if (secondsLeft >= 0)
      snprintf(buf, sizeof(buf), "auto-connect in %ds    %s", secondsLeft,
               count == 2 ? "Red / Blue = pick" : "Red = next   Blue = OK");
    else
      snprintf(buf, sizeof(buf), "%s",
               count == 2 ? "Red / Blue = pick" : "Red = next   Blue = OK");
    tft.drawString(buf, W / 2, fy + 3, 2);
  }
  g_menuSel  = -999;  // WiFi picker was shown; force game-menu full-repaint next
  g_menuSecs = -999;
}

void lcdBlank() {
  tft.fillScreen(TFT_BLACK);
  lcdForceRepaint();  // next lcdShowGame() fully redraws when we wake
}

void lcdShowGameMenu(const char *title, const char *const labels[], int count,
                     int sel, int secondsLeft) {
  const int W = tft.width();
  const int H = tft.height();

  if (sel != g_menuSel) {
    g_menuSel   = sel;
    g_menuSecs  = -999;   // force footer repaint
    g_pickerSel = -999;   // force WiFi-picker full-repaint if shown next
    tft.fillScreen(TFT_BLACK);
    tft.setTextColor(TFT_WHITE, TFT_BLACK);
    tft.setTextDatum(TC_DATUM);
    tft.drawString(title, W / 2, 6, 4);

    const int top = 42, footer = 24, gap = 6;
    const int n = (count < 1) ? 1 : count;
    int rowH = (H - top - footer - (n - 1) * gap) / n;
    if (rowH > 44) rowH = 44;
    const int font = (rowH >= 34) ? 4 : 2;  // shrink text when rows get tight

    for (int i = 0; i < count; i++) {
      const int y = top + i * (rowH + gap);
      const bool hi = (i == sel);
      const uint16_t bg = hi ? tft.color565(0, 110, 0) : tft.color565(30, 30, 30);
      tft.fillRoundRect(10, y, W - 20, rowH, 6, bg);
      if (hi) tft.drawRoundRect(10, y, W - 20, rowH, 6, TFT_WHITE);
      tft.setTextColor(TFT_WHITE, bg);
      tft.setTextDatum(ML_DATUM);
      tft.drawString(labels[i], 22, y + rowH / 2, font);
    }
  }

  if (secondsLeft != g_menuSecs) {
    g_menuSecs = secondsLeft;
    const int fy = H - 22;
    tft.fillRect(0, fy, W, 22, TFT_BLACK);
    tft.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    tft.setTextDatum(TC_DATUM);
    char buf[64];
    if (secondsLeft >= 0)
      snprintf(buf, sizeof(buf), "auto in %ds    Red = next   Blue = OK",
               secondsLeft);
    else
      snprintf(buf, sizeof(buf), "Red = next    Blue = select");
    tft.drawString(buf, W / 2, fy + 2, 2);
  }
}

void lcdForceRepaint() {
  g_redBright = g_blueBright = -1;
  g_lastRedT = g_lastBlueT = g_lastStatus = "";
  g_lastBarPct = -1;
}
