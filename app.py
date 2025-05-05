from flask import Flask, jsonify
from flask_cors import CORS
import paho.mqtt.client as mqtt
import json
from datetime import datetime

app = Flask(__name__)
CORS(app)

latest_data = {
    "atmosphere": {},
    "signalk": {}
}

# MQTT callback

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        topic = msg.topic

        if topic.startswith("signalk/"):
            values = data.get("updates", [{}])[0].get("values", [])
            for item in values:
                path = item.get("path")
                value = item.get("value")
                if path == "environment.wind.speedOverGround":
                    latest_data["signalk"]["wind_speed_true"] = round(value * 1.94384, 2)  # m/s to knots
                elif path == "environment.outside.temperature":
                    latest_data["signalk"]["outside_temperature"] = round((value - 273.15) * 9/5 + 32, 1)  # K to °F
                elif path == "environment.outside.pressure":
                    latest_data["signalk"]["atmospheric_pressure"] = round(value / 100, 1)  # Pa to hPa
        else:
            latest_data['atmosphere'] = data
            latest_data['atmosphere']['received_at'] = datetime.utcnow().isoformat()

    except Exception as e:
        print("[MQTT] Error processing message:", e)

# MQTT client setup
mqtt_client = mqtt.Client()
mqtt_client.on_message = on_message
mqtt_client.connect("localhost", 1883, 60)
mqtt_client.subscribe("oceanpi/atmosphere")
mqtt_client.subscribe("signalk/#")
mqtt_client.loop_start()

# API endpoints
@app.route("/api/atmosphere")
def get_atmosphere():
    return jsonify(latest_data["atmosphere"])

@app.route("/api/signalk")
def get_signalk():
    return jsonify(latest_data["signalk"])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
