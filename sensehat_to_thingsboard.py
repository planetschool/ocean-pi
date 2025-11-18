import time
import json
from sense_hat import SenseHat
import paho.mqtt.client as mqtt

ACCESS_TOKEN = "this is a secret"
THINGSBOARD_HOST = "thingsboard.cloud"
PORT = 1883
PUBLISH_INTERVAL = 10  # seconds

sense = SenseHat()

client = mqtt.Client()
client.username_pw_set(ACCESS_TOKEN)
client.connect(THINGSBOARD_HOST, PORT, 60)
client.loop_start()

while True:
    data = {
        "temperature": sense.get_temperature(),
        "humidity": sense.get_humidity(),
        "pressure": sense.get_pressure(),
        "orientation": sense.get_orientation(),
        "acceleration": sense.get_accelerometer_raw(),
        "gyroscope": sense.get_gyroscope_raw(),
    }

    client.publish("v1/devices/me/telemetry", json.dumps(data))
    print("Published:", data)
    time.sleep(PUBLISH_INTERVAL)
