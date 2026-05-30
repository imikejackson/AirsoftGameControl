//
// epaper.cpp — Status display implementation.
//
// Panel: Waveshare 2.13" V1, ribbon HINK-E0213-A01 / SYX1726 (2017) =
// GDE0213B1 (IL3895), 122x250 -> GxEPD2_213. Pins CS=5, DC=17, RST=16, BUSY=4;
// hardware VSPI CLK=18, DIN=23 (configured by display.init()).
//
// NOTE (see config.h): these SPI pins collide with the TM1637 displays and the
// LED data pin in the control-point reference pinout. Resolve before building a
// node that uses both the e-paper and the TM1637s.
//
#include "epaper.h"

#include <GxEPD2_BW.h>
#include <Fonts/FreeMonoBold9pt7b.h>
#include <Fonts/FreeMono9pt7b.h>

namespace {

GxEPD2_BW<GxEPD2_213, GxEPD2_213::HEIGHT> display(
    GxEPD2_213(/*CS*/ 5, /*DC*/ 17, /*RST*/ 16, /*BUSY*/ 4));

// Tracks what is currently on the panel so we skip redundant (slow) refreshes.
String g_shown = "<uninitialized>";

// Build a single string that captures everything visible. If it matches what is
// already shown, there is nothing to redraw.
String renderKey(const String &nodeName, const char *nodeType, bool connected,
                 const String &ssid, const String &ip) {
  return String(nodeType) + "|" + nodeName + "|" +
         (connected ? "up" : "down") + "|" + ssid + "|" + ip;
}

void drawScreen(const String &nodeName, const char *nodeType, bool connected,
                const String &ssid, const String &ip) {
  String name = nodeName;
  name.toUpperCase();
  String type = String(nodeType);
  type.toUpperCase();

  display.setRotation(1);  // landscape: 250 wide x 122 tall
  display.setTextColor(GxEPD_BLACK);
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);

    // Node type label (small) and big control-point name.
    display.setFont(&FreeMono9pt7b);
    display.setTextSize(1);
    display.setCursor(4, 16);
    display.print(type);

    display.setFont(&FreeMonoBold9pt7b);
    display.setTextSize(2);
    display.setCursor(4, 48);
    display.print(name);

    // Divider.
    display.drawFastHLine(0, 58, display.width(), GxEPD_BLACK);

    // Network details.
    display.setFont(&FreeMono9pt7b);
    display.setTextSize(1);

    display.setCursor(4, 78);
    display.print("Net: ");
    display.print(connected ? ssid : String("(connecting)"));

    display.setCursor(4, 98);
    display.print("IP : ");
    display.print(connected ? ip : String("--"));

    display.setCursor(4, 118);
    display.print(connected ? "Status: ONLINE" : "Status: offline");
  } while (display.nextPage());

  display.hibernate();  // low power; keeps the image without refreshing
}

}  // namespace

void epaperSetup() {
  // REQUIRED before any drawing: configures CS/DC/RST/BUSY pins, calls
  // SPI.begin() (CLK=18, DIN=23), and resets the panel. Without it, no bytes
  // reach the display.
  display.init(115200);
  g_shown = "<uninitialized>";  // force the first real update to draw
}

void epaperUpdateStatus(const String &nodeName, const char *nodeType,
                        bool connected, const String &ssid, const String &ip) {
  String key = renderKey(nodeName, nodeType, connected, ssid, ip);
  if (key == g_shown) return;  // nothing changed — skip the slow refresh

  drawScreen(nodeName, nodeType, connected, ssid, ip);
  g_shown = key;
}
