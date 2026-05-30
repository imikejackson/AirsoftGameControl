#pragma once
//
// mqtt.h — MQTT reporting + command channel for all node types.
//
// MQTT is how nodes report state to the central server and receive commands.
// It is strictly for REPORTING — the game runs locally regardless of broker
// state (CLAUDE.md: "Local state is authoritative"). Fully non-blocking:
// mqttLoop() drives connect/reconnect with backoff and services the client.
//
// Topic schema (see CLAUDE.md), base = airsoft/<node_type>/<node_id>:
//   <base>/state       node publishes state (retained)
//   <base>/command     node subscribes for commands (reset, etc.)
//   <base>/status      LWT online/offline (retained)
//   <base>/heartbeat   periodic alive signal
//   airsoft/game/state    current game mode/score (subscribed)
//   airsoft/game/command  server commands to all nodes (subscribed)
//
// NOTE on QoS: PubSubClient only publishes at QoS 0. We rely on RETAINED
// messages so the broker always serves the latest state to new subscribers
// (e.g. the dashboard), and subscribe at QoS 1. This is the practical
// equivalent of "QoS 1 retained" for this library.
//
#include <Arduino.h>

// Handler for inbound commands. `topic` is the full topic, `payload` the raw
// message body. Registered by the game layer to act on commands.
typedef void (*MqttCommandHandler)(const String &topic, const String &payload);

// Call once in setup(), after networkSetup(). Loads broker config from NVS,
// configures the client + Last Will, but does not block on connection.
void mqttSetup();

// Call every loop() iteration. Non-blocking: drives reconnect backoff (only
// while WiFi is up) and services inbound messages + heartbeats.
void mqttLoop();

bool   mqttConnected();
String mqttStatusString();

// Publish the node's state as a retained JSON payload on <base>/state. The
// game layer calls this whenever authoritative state changes.
void mqttPublishState(const String &jsonPayload);

// Register the inbound command handler (one handler; last registration wins).
void mqttSetCommandHandler(MqttCommandHandler handler);

// --- Runtime (re)provisioning over Serial -----------------------------------
void setMqttBroker(const String &host, uint16_t port);
const String &mqttBrokerHost();
uint16_t      mqttBrokerPort();

// Parse a single Serial command line (already read + trimmed by main).
// Returns true if handled. Recognized:
//   mqtt <host> <port>   set + save broker, reconnect
//   mqttstatus           print mqttStatusString()
bool handleMqttSerialCommand(const String &line);
