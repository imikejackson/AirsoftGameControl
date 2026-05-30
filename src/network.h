#pragma once
//
// network.h — WiFi connectivity for all node types.
//
// This module owns the radio. It is fully non-blocking: networkSetup() kicks
// off the first connection attempt and returns immediately; networkLoop() must
// be called every iteration of the main loop() to drive the connection state
// machine and handle reconnection. The game (buttons, displays, LEDs) keeps
// running regardless of network state — WiFi is for reporting, never for
// running the game (see CLAUDE.md: "Local state is authoritative").
//
// MQTT and OTA will be layered into this same module later. They will hook off
// the WiFi-connected transition exposed here.
//
#include <Arduino.h>

// Call once from setup(). Loads node ID + credentials from NVS (seeding from
// secrets.h defaults on first boot), brings up the STA interface, and starts
// the first connection attempt. Does NOT block waiting for the connection.
void networkSetup();

// Call every loop() iteration. Drives the non-blocking connect/reconnect state
// machine with backoff. Returns quickly; never blocks.
void networkLoop();

// True once the STA interface has an IP address.
bool wifiConnected();

// Human-readable one-line status, e.g. "connected 192.168.1.42 (rssi -57)".
// Useful for Serial logging and (later) heartbeat payloads.
String wifiStatusString();

// The SSID we are configured to join (the access point name).
const String &wifiSsid();

// Current IP as a string, or "0.0.0.0" when not connected.
String wifiIpString();

// The node's identity, loaded from NVS. Stable for the life of the boot.
const String &nodeId();
const char   *nodeTypeStr();

// The DHCP/mDNS hostname this node advertises, e.g.
// "airsoft-controlpoint-alpha".
const String &nodeHostname();

// --- Runtime (re)provisioning ---------------------------------------------
// Persist new values to NVS. Credential changes trigger an immediate
// reconnect with the new SSID/password; the node ID change takes effect on
// next boot (it is baked into the hostname). These let you configure a sealed
// node over the Serial console without reflashing — see handleSerialConfig().
void setWifiCredentials(const String &ssid, const String &password);
void setNodeId(const String &id);

// Optional helper: parse simple Serial provisioning commands. Call from
// loop() if you want runtime config over the Serial console. Recognized:
//   wifi <ssid> <password>   set + save WiFi credentials, reconnect
//   nodeid <id>              set + save node ID (reboot to apply hostname)
//   netstatus                print wifiStatusString()
void handleSerialConfig();
