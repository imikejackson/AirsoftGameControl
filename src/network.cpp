//
// network.cpp — Non-blocking WiFi for the Airsoft Control Point System.
//
// Design notes:
//  * State machine driven by networkLoop(); no blocking waits, no delay().
//  * Credentials and node ID live in NVS (Preferences). secrets.h only seeds
//    NVS on first boot, so a flashed-but-unprovisioned node still has defaults.
//  * Reconnection uses exponential backoff capped at WIFI_RETRY_INTERVAL_MAX_MS
//    so a downed AP doesn't get hammered.
//  * WiFi events are used for logging only; control flow polls WiFi.status()
//    and an explicit state enum so the logic is easy to follow.
//
#include "network.h"
#include "config.h"
#include "secrets.h"

#include <WiFi.h>
#include <Preferences.h>

// Preset WiFi networks for the on-boot picker. Defined in secrets.h; fall back
// to a single preset built from the DEFAULT_* creds if not provided.
#ifndef WIFI_PRESETS
#define WIFI_PRESETS { { "Default", DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASS } }
#endif

namespace {

struct WifiPreset { const char *label; const char *ssid; const char *pass; };
const WifiPreset kPresets[] = WIFI_PRESETS;
const int        kPresetCount = (int)(sizeof(kPresets) / sizeof(kPresets[0]));

enum NetState {
  NET_IDLE,        // not yet started / no usable credentials
  NET_CONNECTING,  // WiFi.begin() issued, waiting for result
  NET_CONNECTED,   // have an IP
  NET_BACKOFF      // last attempt failed; waiting before retrying
};

Preferences prefs;

String      g_nodeId;
String      g_hostname;
String      g_ssid;
String      g_pass;

NetState      g_state            = NET_IDLE;
unsigned long g_stateSince       = 0;        // millis() of last state change
unsigned long g_backoffInterval  = WIFI_RETRY_INTERVAL_MS;
bool          g_loggedConnected  = false;

// --- NVS helpers -----------------------------------------------------------

void loadConfig() {
  prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);

  g_nodeId = prefs.getString("node_id", DEFAULT_NODE_ID);
  g_ssid   = prefs.getString("wifi_ssid", DEFAULT_WIFI_SSID);
  g_pass   = prefs.getString("wifi_pass", DEFAULT_WIFI_PASS);

  // Persist the seeded defaults so the first explicit read is authoritative
  // and a later secrets.h change won't silently override a provisioned node.
  if (!prefs.isKey("node_id"))   prefs.putString("node_id", g_nodeId);
  if (!prefs.isKey("wifi_ssid")) prefs.putString("wifi_ssid", g_ssid);
  if (!prefs.isKey("wifi_pass")) prefs.putString("wifi_pass", g_pass);

  // Re-sync with the compiled-in presets. A node that last picked a preset
  // (wifi_preset >= 0) keeps a COPY of that preset's ssid/pass in NVS. If
  // secrets.h has since changed that slot (a network renamed or replaced), the
  // copy points at a network the picker no longer offers, and the "keep
  // last-used" timeout would leave the node stranded on it. Adopt the current
  // preset instead. Credentials typed over Serial store wifi_preset = -1 and
  // are left untouched.
  {
    int idx = prefs.getInt("wifi_preset", 0);
    if (idx >= 0 && idx < kPresetCount &&
        (g_ssid != kPresets[idx].ssid || g_pass != kPresets[idx].pass)) {
      // Prefer whichever preset still carries the stored SSID (slots moved).
      for (int i = 0; i < kPresetCount; i++) {
        if (g_ssid == kPresets[i].ssid) { idx = i; break; }
      }
      Serial.printf("[wifi] stored creds \"%s\" out of sync with preset %d; "
                    "adopting \"%s\"\n",
                    g_ssid.c_str(), idx, kPresets[idx].ssid);
      g_ssid = kPresets[idx].ssid;
      g_pass = kPresets[idx].pass;
      prefs.putString("wifi_ssid", g_ssid);
      prefs.putString("wifi_pass", g_pass);
      prefs.putInt("wifi_preset", idx);
    }
  }

  prefs.end();

  g_hostname = String(HOSTNAME_PREFIX) + "-" + NODE_TYPE_STR + "-" + g_nodeId;
}

bool credentialsLookValid() {
  return g_ssid.length() > 0 && g_ssid != "YOUR_FIELD_SSID";
}

// --- State transitions -----------------------------------------------------

void enterState(NetState s) {
  g_state      = s;
  g_stateSince = millis();
}

void beginConnect() {
  Serial.printf("[wifi] connecting to \"%s\" as %s ...\n",
                g_ssid.c_str(), g_hostname.c_str());
  WiFi.disconnect(/*wifioff=*/false, /*eraseap=*/true);
  WiFi.begin(g_ssid.c_str(), g_pass.c_str());
  g_loggedConnected = false;
  enterState(NET_CONNECTING);
}

// --- WiFi event logging ----------------------------------------------------

void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.printf("[wifi] got IP %s (rssi %d)\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      // Logged here rather than in the loop to capture the reason code.
      Serial.printf("[wifi] disconnected (reason %u)\n",
                    info.wifi_sta_disconnected.reason);
      break;
    default:
      break;
  }
}

}  // namespace

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

void networkSetup() {
  loadConfig();

  WiFi.persistent(false);          // we manage credentials in NVS ourselves
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);    // we drive reconnection explicitly
  WiFi.setSleep(false);            // lower latency; nodes are mains-powered
  WiFi.setHostname(g_hostname.c_str());
  WiFi.onEvent(onWiFiEvent);

  Serial.printf("[net] node %s/%s, hostname %s\n",
                NODE_TYPE_STR, g_nodeId.c_str(), g_hostname.c_str());

  if (credentialsLookValid()) {
    beginConnect();
  } else {
    Serial.println("[wifi] no valid credentials — set with: wifi <ssid> <pass>");
    enterState(NET_IDLE);
  }
}

void networkLoop() {
  const unsigned long now     = millis();
  const unsigned long elapsed = now - g_stateSince;

  switch (g_state) {
    case NET_IDLE:
      // Nothing to do until credentials are provisioned (over Serial).
      break;

    case NET_CONNECTING:
      if (WiFi.status() == WL_CONNECTED) {
        g_backoffInterval = WIFI_RETRY_INTERVAL_MS;  // reset backoff
        enterState(NET_CONNECTED);
      } else if (elapsed >= WIFI_CONNECT_TIMEOUT_MS) {
        Serial.printf("[wifi] connect timed out after %lums; backing off %lums\n",
                      elapsed, g_backoffInterval);
        enterState(NET_BACKOFF);
      }
      break;

    case NET_CONNECTED:
      if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[wifi] connection lost");
        enterState(NET_BACKOFF);
      } else if (!g_loggedConnected) {
        g_loggedConnected = true;
        Serial.printf("[wifi] %s\n", wifiStatusString().c_str());
      }
      break;

    case NET_BACKOFF:
      if (elapsed >= g_backoffInterval) {
        // Exponential backoff, capped.
        g_backoffInterval =
            min(g_backoffInterval * 2, (unsigned long)WIFI_RETRY_INTERVAL_MAX_MS);
        beginConnect();
      }
      break;
  }
}

bool wifiConnected() {
  return g_state == NET_CONNECTED && WiFi.status() == WL_CONNECTED;
}

String wifiStatusString() {
  if (wifiConnected()) {
    return "connected " + WiFi.localIP().toString() +
           " (rssi " + String(WiFi.RSSI()) + ")";
  }
  switch (g_state) {
    case NET_CONNECTING: return "connecting to " + g_ssid;
    case NET_BACKOFF:    return "disconnected (retrying)";
    case NET_IDLE:       return "idle (unprovisioned)";
    default:             return "disconnected";
  }
}

const String &nodeId()       { return g_nodeId; }
const char   *nodeTypeStr()  { return NODE_TYPE_STR; }
const String &nodeHostname() { return g_hostname; }
const String &wifiSsid()     { return g_ssid; }

String wifiIpString() {
  return wifiConnected() ? WiFi.localIP().toString() : String("0.0.0.0");
}

// ---------------------------------------------------------------------------
// WiFi presets + on-boot picker
// ---------------------------------------------------------------------------

int networkPresetCount() { return kPresetCount; }

const char *networkPresetLabel(int i) {
  return (i >= 0 && i < kPresetCount) ? kPresets[i].label : "";
}

const char *networkPresetSsid(int i) {
  return (i >= 0 && i < kPresetCount) ? kPresets[i].ssid : "";
}

int networkLastPresetIndex() {
  prefs.begin(NVS_NAMESPACE, /*readOnly=*/true);
  int i = prefs.getInt("wifi_preset", 0);
  prefs.end();
  if (i < 0 || i >= kPresetCount) i = 0;
  return i;
}

void networkApplyPreset(int i) {
  if (i < 0 || i >= kPresetCount) return;
  g_ssid = kPresets[i].ssid;
  g_pass = kPresets[i].pass;
  prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);
  prefs.putString("wifi_ssid", g_ssid);
  prefs.putString("wifi_pass", g_pass);
  prefs.putInt("wifi_preset", i);
  prefs.end();
  Serial.printf("[wifi] preset %d selected: %s (%s)\n", i, kPresets[i].label,
                g_ssid.c_str());
}

void networkReconnect() {
  // Used when the network is re-picked at runtime: drop the current link and
  // reconnect with the credentials now in g_ssid/g_pass.
  if (!credentialsLookValid()) return;
  g_backoffInterval = WIFI_RETRY_INTERVAL_MS;
  beginConnect();
}

// ---------------------------------------------------------------------------
// Runtime provisioning
// ---------------------------------------------------------------------------

void setWifiCredentials(const String &ssid, const String &password) {
  g_ssid = ssid;
  g_pass = password;

  prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);
  prefs.putString("wifi_ssid", g_ssid);
  prefs.putString("wifi_pass", g_pass);
  prefs.putInt("wifi_preset", -1);  // custom creds: don't re-sync to a preset
  prefs.end();

  Serial.printf("[wifi] credentials updated; reconnecting to \"%s\"\n",
                g_ssid.c_str());
  g_backoffInterval = WIFI_RETRY_INTERVAL_MS;
  beginConnect();
}

void setNodeId(const String &id) {
  g_nodeId = id;
  prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);
  prefs.putString("node_id", g_nodeId);
  prefs.end();
  Serial.printf("[net] node ID set to \"%s\" (reboot to apply hostname)\n",
                g_nodeId.c_str());
}

bool handleNetworkSerialCommand(const String &line) {
  if (line.startsWith("wifi ")) {
    String rest = line.substring(5);
    rest.trim();
    // SSIDs routinely contain spaces ("MKAirsoft Middletown"), so splitting on
    // the FIRST space silently truncates them — the node then hunts for a
    // network that doesn't exist. Two accepted forms:
    //   wifi "My Network" secretpass   quoted SSID; use this if the PASSWORD
    //                                  itself contains spaces
    //   wifi My Network secretpass     unquoted; split on the LAST space
    String ssid, pass;
    if (rest.startsWith("\"")) {
      const int close = rest.indexOf('"', 1);
      if (close < 0) {
        Serial.println("[cfg] usage: wifi \"<ssid>\" <password>  (unclosed quote)");
        return true;
      }
      ssid = rest.substring(1, close);
      pass = rest.substring(close + 1);
      pass.trim();
    } else {
      const int sp = rest.lastIndexOf(' ');
      if (sp < 0) {
        Serial.println("[cfg] usage: wifi <ssid> <password>");
        return true;
      }
      ssid = rest.substring(0, sp);
      pass = rest.substring(sp + 1);
      ssid.trim();
    }
    if (ssid.length() == 0 || pass.length() == 0) {
      Serial.println("[cfg] usage: wifi <ssid> <password>");
      return true;
    }
    setWifiCredentials(ssid, pass);
    return true;
  } else if (line.startsWith("nodeid ")) {
    String id = line.substring(7);
    id.trim();
    if (id.length()) setNodeId(id);
    return true;
  } else if (line == "netstatus") {
    Serial.printf("[net] %s\n", wifiStatusString().c_str());
    return true;
  } else if (line == "presets") {
    const int last = networkLastPresetIndex();
    for (int i = 0; i < kPresetCount; i++) {
      Serial.printf("[cfg] preset %d: %-14s \"%s\"%s\n", i, kPresets[i].label,
                    kPresets[i].ssid, (i == last) ? "  (current)" : "");
    }
    return true;
  } else if (line.startsWith("preset ")) {
    // Bench provisioning: pick a compiled-in network by index without touching
    // the buttons/LCD. Same effect as choosing it in the boot picker.
    const int i = line.substring(7).toInt();
    if (i < 0 || i >= kPresetCount || !isDigit(line.charAt(7))) {
      Serial.printf("[cfg] usage: preset <0..%d>  (see: presets)\n",
                    kPresetCount - 1);
      return true;
    }
    networkApplyPreset(i);
    networkReconnect();
    return true;
  }
  return false;
}
