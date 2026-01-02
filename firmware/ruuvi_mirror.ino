/*
 * Project: RuuviMirror
 * Description: Subscribes to ruuvi_data and republishes the payload.
 */

#include "Particle.h"

void handleRuuviData(const char *event, const char *data);

void setup() {
  // Subscribe to "ruuvi_data" events from MY_DEVICES
  Particle.subscribe("ruuvi_data", handleRuuviData, MY_DEVICES);
}

void loop() {
  // Nothing to do here
}

void handleRuuviData(const char *event, const char *data) {
  // Copy the data to a local String to prevent memory corruption.
  // The 'data' pointer might point to a shared buffer that gets overwritten
  // when Particle.publish prepares the outgoing message.
  String payload = data ? String(data) : "";
  Particle.publish("mirror/ruuvi_data", payload, PRIVATE);
}