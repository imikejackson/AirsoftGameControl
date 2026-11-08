"""Constants shared across the server."""
import os

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOUNDS_DIR = os.path.join(SERVER_DIR, "sounds")
TEMPLATES_DIR = os.path.join(SERVER_DIR, "templates")

DASH_VERSION = 18           # bump on every dashboard change; shown in the header
MQTT_HOST = "localhost"
MQTT_PORT = 1883
TOPIC = "airsoft/#"
HTTP_PORT = 8080
DEFAULT_DURATION_S = 15 * 60

# Friendly display names per node_id (mirrors NODE_LABELS in the firmware's
# config.h). node_id stays the identifier on the MQTT topics; this is just for
# display. A node_id not listed here falls back to showing its id.
NODE_LABELS = {"alpha": "Pink Hallway", "bravo": "Kill House", "charlie": "Dark Room"}
