import time
import json
from sense_hat import SenseHat
import paho.mqtt.client as mqtt
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from PIL import Image
import io
import base64
import time
import os

ACCESS_TOKEN = os.environ.get("THINGSBOARD_TOKEN")
THINGSBOARD_HOST = "thingsboard.cloud"
PORT = 1883
SENSEHAT_INTERVAL = 2  # seconds
CAMERA_INTERVAL = 10  # seconds

sense = SenseHat()

client = mqtt.Client()
client.username_pw_set(ACCESS_TOKEN)
client.connect(THINGSBOARD_HOST, PORT, 60)
client.loop_start()

#----------------------------------------------------------------------
# --- Camera Setup --- #
#----------------------------------------------------------------------
Camera_On = True
picam2 = Picamera2()
config = picam2.create_still_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()

def create_snapshot():
	# Capture raw RGB frame
	frame = picam2.capture_array()

	# Encode to JPEG with given quality
	buf = io.BytesIO()
	Image.fromarray(frame).save(buf, format="JPEG", quality=50)   # <-- control size here
	jpeg_bytes = buf.getvalue()
	return jpeg_bytes

counter = 0

while True:
    color = sense.color
    
    data = {
        "temperature": sense.get_temperature(),
        "humidity": sense.get_humidity(),
        "pressure": sense.get_pressure(),
        "orientation": sense.get_orientation(),
        "acceleration": sense.get_accelerometer_raw(),
        "gyroscope": sense.get_gyroscope_raw(),
        "color": (color.red, color.green, color.blue),
    }

    if Camera_On and counter == CAMERA_INTERVAL:
        jpeg_bytes = create_snapshot()
        pic = base64.b64encode(jpeg_bytes).decode("utf-8")
        print("length of the pic is:", len(pic))
        data["snapshot"] = pic
        counter = 0

    client.publish("v1/devices/me/telemetry", json.dumps(data))
    print("Published:", data)
    time.sleep(SENSEHAT_INTERVAL)
    counter += 1
