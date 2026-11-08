"""The MQTT client loop (runs in its own thread, reconnects forever)."""
import time

import paho.mqtt.client as mqtt

from . import boxes, config, hub


def _on_connect(client, userdata, flags, rc, *args):
    print(f"[dash] connected to broker (rc={rc}); subscribing to {config.TOPIC}")
    client.subscribe(config.TOPIC)
    hub.publish_game()  # establish the current (idle) game state on the bus


def run():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)  # paho 2.x
    except (AttributeError, TypeError):
        client = mqtt.Client()                                  # paho 1.x
    client.on_connect = _on_connect
    client.on_message = boxes.on_message
    hub.client = client
    while True:
        try:
            client.connect(config.MQTT_HOST, config.MQTT_PORT, 60)
            client.loop_forever()
        except Exception as e:  # noqa: BLE001 — keep the bridge alive
            print(f"[dash] mqtt error: {e}; retrying in 3s")
            time.sleep(3)
