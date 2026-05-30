//
// mqtt.cpp — MQTT client implementation.
//
// Non-blocking connect/reconnect with exponential backoff (only attempted when
// WiFi is up). On connect: registers an "offline" Last Will, publishes
// "online" + a retained state snapshot, and subscribes to this node's command
// topic plus the shared game topics. Publishes a heartbeat every ~12s.
//
#include "mqtt.h"
#include "config.h"
#include "network.h"

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>

namespace {

WiFiClient   g_wifiClient;
PubSubClient g_client(g_wifiClient);
Preferences  g_prefs;

String   g_host;
uint16_t g_port = DEFAULT_MQTT_PORT;

// Topics (built once in setup from node identity).
String g_baseTopic;     // airsoft/<type>/<id>
String g_topicState;
String g_topicCommand;
String g_topicStatus;
String g_topicHeartbeat;

const char *kGameState   = "airsoft/game/state";
const char *kGameCommand = "airsoft/game/command";

MqttCommandHandler g_handler = nullptr;

unsigned long g_lastAttempt   = 0;
unsigned long g_backoff       = MQTT_RETRY_INTERVAL_MS;
unsigned long g_lastHeartbeat = 0;
bool          g_everConnected = false;

// --- NVS ------------------------------------------------------------------

void loadConfig() {
  g_prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);
  g_host = g_prefs.getString("mqtt_host", DEFAULT_MQTT_HOST);
  g_port = g_prefs.getUShort("mqtt_port", DEFAULT_MQTT_PORT);
  if (!g_prefs.isKey("mqtt_host")) g_prefs.putString("mqtt_host", g_host);
  if (!g_prefs.isKey("mqtt_port")) g_prefs.putUShort("mqtt_port", g_port);
  g_prefs.end();
}

// --- Inbound --------------------------------------------------------------

void onMessage(char *topic, byte *payload, unsigned int length) {
  String t(topic);
  String body;
  body.reserve(length);
  for (unsigned int i = 0; i < length; i++) body += (char)payload[i];

  Serial.printf("[mqtt] rx %s = %s\n", t.c_str(), body.c_str());
  if (g_handler) g_handler(t, body);
}

// --- State / heartbeat payloads -------------------------------------------

void publishStateSnapshot() {
  JsonDocument doc;
  doc["node"]   = nodeId();
  doc["type"]   = nodeTypeStr();
  doc["ip"]     = wifiIpString();
  doc["rssi"]   = WiFi.RSSI();
  doc["online"] = true;
  String out;
  serializeJson(doc, out);
  g_client.publish(g_topicState.c_str(), out.c_str(), /*retained=*/true);
}

void publishHeartbeat() {
  JsonDocument doc;
  doc["uptime_s"] = (uint32_t)(millis() / 1000);
  doc["rssi"]     = WiFi.RSSI();
  doc["ip"]       = wifiIpString();
  String out;
  serializeJson(doc, out);
  g_client.publish(g_topicHeartbeat.c_str(), out.c_str());
}

// --- Connect --------------------------------------------------------------

void attemptConnect() {
  g_lastAttempt = millis();
  Serial.printf("[mqtt] connecting to %s:%u ...\n", g_host.c_str(), g_port);

  String clientId = nodeHostname();
  // connect(id, user, pass, willTopic, willQoS, willRetain, willMessage)
  bool ok = g_client.connect(clientId.c_str(), nullptr, nullptr,
                             g_topicStatus.c_str(), 1, true, "offline");
  if (!ok) {
    g_backoff = min(g_backoff * 2, (unsigned long)MQTT_RETRY_INTERVAL_MAX_MS);
    Serial.printf("[mqtt] connect failed (rc=%d); retry in %lums\n",
                  g_client.state(), g_backoff);
    return;
  }

  g_backoff = MQTT_RETRY_INTERVAL_MS;  // reset backoff
  g_everConnected = true;
  Serial.printf("[mqtt] connected as %s\n", clientId.c_str());

  // Announce online, publish current state, and subscribe.
  g_client.publish(g_topicStatus.c_str(), "online", /*retained=*/true);
  publishStateSnapshot();
  g_client.subscribe(g_topicCommand.c_str(), 1);
  g_client.subscribe(kGameCommand, 1);
  g_client.subscribe(kGameState, 1);
  g_lastHeartbeat = millis();
}

}  // namespace

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

void mqttSetup() {
  loadConfig();

  g_baseTopic      = String("airsoft/") + nodeTypeStr() + "/" + nodeId();
  g_topicState     = g_baseTopic + "/state";
  g_topicCommand   = g_baseTopic + "/command";
  g_topicStatus    = g_baseTopic + "/status";
  g_topicHeartbeat = g_baseTopic + "/heartbeat";

  g_client.setServer(g_host.c_str(), g_port);
  g_client.setBufferSize(MQTT_BUFFER_SIZE);
  g_client.setCallback(onMessage);

  Serial.printf("[mqtt] broker %s:%u, base topic %s\n",
                g_host.c_str(), g_port, g_baseTopic.c_str());
}

void mqttLoop() {
  if (!wifiConnected()) return;  // MQTT needs the network first

  if (!g_client.connected()) {
    if (millis() - g_lastAttempt >= g_backoff) attemptConnect();
    return;
  }

  g_client.loop();

  if (millis() - g_lastHeartbeat >= MQTT_HEARTBEAT_INTERVAL_MS) {
    g_lastHeartbeat = millis();
    publishHeartbeat();
  }
}

bool mqttConnected() { return g_client.connected(); }

String mqttStatusString() {
  if (g_client.connected()) {
    return "connected " + g_host + ":" + String(g_port);
  }
  return "disconnected (state " + String(g_client.state()) + ")";
}

void mqttPublishState(const String &jsonPayload) {
  if (!g_client.connected()) return;
  g_client.publish(g_topicState.c_str(), jsonPayload.c_str(), /*retained=*/true);
}

void mqttSetCommandHandler(MqttCommandHandler handler) { g_handler = handler; }

// ---------------------------------------------------------------------------
// Runtime provisioning
// ---------------------------------------------------------------------------

void setMqttBroker(const String &host, uint16_t port) {
  g_host = host;
  g_port = port;

  g_prefs.begin(NVS_NAMESPACE, /*readOnly=*/false);
  g_prefs.putString("mqtt_host", g_host);
  g_prefs.putUShort("mqtt_port", g_port);
  g_prefs.end();

  g_client.setServer(g_host.c_str(), g_port);
  if (g_client.connected()) g_client.disconnect();
  g_backoff = MQTT_RETRY_INTERVAL_MS;
  g_lastAttempt = 0;  // attempt immediately on next loop
  Serial.printf("[mqtt] broker set to %s:%u; reconnecting\n",
                g_host.c_str(), g_port);
}

const String &mqttBrokerHost() { return g_host; }
uint16_t      mqttBrokerPort() { return g_port; }

bool handleMqttSerialCommand(const String &line) {
  if (line.startsWith("mqtt ")) {
    String rest = line.substring(5);
    rest.trim();
    int sp = rest.indexOf(' ');
    String host = (sp < 0) ? rest : rest.substring(0, sp);
    uint16_t port = (sp < 0) ? DEFAULT_MQTT_PORT
                             : (uint16_t)rest.substring(sp + 1).toInt();
    if (host.length()) setMqttBroker(host, port);
    return true;
  } else if (line == "mqttstatus") {
    Serial.printf("[mqtt] %s\n", mqttStatusString().c_str());
    return true;
  }
  return false;
}
