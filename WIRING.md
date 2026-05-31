# Wiring / Pinout — Airsoft Control Point (ESP32)

Reference for the **control point** node (ESP32-WROOM-32U). Pin assignments are
defined in [`src/config.h`](src/config.h); the LCD pins are set via build flags
in [`platformio.ini`](platformio.ini). This file is the human-friendly summary —
if they ever disagree, the source files win.

> Board note: avoid GPIO 6–11 (flash). Strapping pins (0, 2, 12, 15) are usable
> but touchy at boot; the ones in use here (2 for the onboard LED, 5 for the
> future strip) are fine because we only drive them after boot.

## Quick pin map

| GPIO | Connects to | Notes |
|-----:|-------------|-------|
| **25** | **Red button** | other leg → GND, internal pull-up (active-low) |
| **26** | **Blue button** | other leg → GND, internal pull-up (active-low) |
| 27 | Reset button *(optional)* | other leg → GND; not currently installed |
| 2  | Onboard WS2812 RGB LED | on the dev board — no external wiring |
| 18 | LCD **SCL / SCLK** | hardware SPI clock |
| 23 | LCD **SDA / MOSI / DIN** | hardware SPI data |
| 4  | LCD **CS** | chip select |
| 17 | LCD **DC** | data/command |
| 16 | LCD **RST** | reset |
| 21 | OLED **SDA** | I²C (OLED optional / for flag nodes) |
| 22 | OLED **SCL** | I²C |
| 5  | WS2812B strip **DATA** | reserved — not yet wired |

---

## Buttons (2× momentary, active-low)

Plain 2-terminal momentary buttons. One leg to the GPIO, the other to **GND**.
No external resistor — firmware uses `INPUT_PULLUP`, so the pin reads HIGH when
released and LOW when pressed.

| Button | GPIO | Other leg |
|--------|------|-----------|
| **Red**  | **25** | GND |
| **Blue** | **26** | GND |
| Reset (optional, not installed) | 27 | GND |

```
GPIO 25 ──[ RED button ]──┐
GPIO 26 ──[ BLUE button ]─┤
GND ──────────────────────┘
```

There is no physical reset button; reset is done over MQTT, the Serial `reset`
command, or by wiring a button to GPIO 27 later.

## Onboard RGB status LED

A single WS2812/NeoPixel on the dev board, **GPIO 2**. No wiring needed. Shows
the owning team's color (and blinks the capturing team's color during a hold).

## 2" ST7789 LCD (Waveshare ST7789V, 240×320 IPS) — SPI

| LCD pin | ESP32 | Notes |
|---------|-------|-------|
| **VCC** | **3.3 V** | ⚠️ 3.3 V, not 5 V |
| **GND** | GND | |
| **SCL / SCLK** | **GPIO 18** | SPI clock |
| **SDA / MOSI / DIN** | **GPIO 23** | SPI data |
| **CS** | **GPIO 4** | |
| **DC** | **GPIO 17** | |
| **RST** | **GPIO 16** | |
| **BL / BLK** | **3.3 V** | backlight always on |

Driver config (in `platformio.ini` build flags): `ST7789_DRIVER`,
`TFT_RGB_ORDER=TFT_BGR` (this panel is BGR — without it red/blue swap),
`TFT_WIDTH=240`, `TFT_HEIGHT=320`, and the pins above.

## SSD1306 OLED (0.96" 128×64, optional) — I²C

Used on flag/referee nodes (or for bring-up). Auto-detected at boot.

| OLED pin | ESP32 |
|----------|-------|
| VCC | 3.3 V |
| GND | GND |
| **SDA** | **GPIO 21** |
| **SCL** | **GPIO 22** |

I²C address `0x3C`.

## WS2812B ownership strip (planned, not yet wired)

| Strip | ESP32 |
|-------|-------|
| DATA | **GPIO 5** (via 330–470 Ω inline resistor) |
| 5V | 5 V supply |
| GND | GND (common with ESP32) |

Add a ~1000 µF capacitor across the strip's 5 V / GND at the injection point.

---

## Power

- ESP32 powered via USB (CH340K) during development, or 5 V.
- The LCD and OLED run on **3.3 V** logic; the WS2812B strip runs on **5 V**.
- Keep all grounds common.
