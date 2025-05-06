from flask import Flask, jsonify
from flask_cors import CORS
import paho.mqtt.client as mqtt
import json
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
import time

app = Flask(__name__)
CORS(app)

# === PostgreSQL connection ===
DATABASE_URL = os.environ.get("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Base = declarative_base()

class SensorReading(Base):
    __tablename__ = 'sensor_readings'
    id = Column(Integer, primary_key=True)
    topic = Column(String)
    payload = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# === MQTT Setup ===
mqtt_broker = os.environ.get("MQTT_BROKER")
mqtt_port = 8883
mqtt_username = os.environ.get("MQTT_USERNAME")
mqtt_password = os.environ.get("MQTT_PASSWORD")

def on_connect(client, userdata, flags, rc):
    print("✅ MQTT connected with result code", rc)
    client.subscribe("oceanpi/#")

def on_disconnect(client, userdata, rc):
    print("❌ MQTT disconnected with result code", rc)
    if rc != 0:
        while True:
            try:
                print("🔄 Trying to reconnect to MQTT broker...")
                client.reconnect()
                break
            except Exception as e:
                print("Reconnect failed:", e)
                time.sleep(5)

def on_message(client, userdata, msg):
    print(f"Received message on {msg.topic}: {msg.payload.decode()}")
    for attempt in range(3):
        try:
            session = Session()
            reading = SensorReading(topic=msg.topic, payload=msg.payload.decode())
            session.add(reading)
            session.commit()
            break
        except Exception as e:
            print(f"DB write failed on attempt {attempt+1}: {e}")
            time.sleep(2)
        finally:
            session.close()

mqtt_client = mqtt.Client()
mqtt_client.username_pw_set(mqtt_username, mqtt_password)
mqtt_client.tls_set()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(mqtt_broker, mqtt_port)
mqtt_client.loop_start()
mqtt_client.on_disconnect = on_disconnect

@app.route("/")
def index():
    return "Ocean Pi Flask Backend is running!"

@app.route("/readings", methods=["GET"])
def get_latest_payload():
    session = Session()
    try:
        latest = (
            session.query(SensorReading)
            .filter(SensorReading.topic == "oceanpi/atmosphere")
            .order_by(SensorReading.timestamp.desc())
            .first()
        )

        if latest is None:
            return jsonify({"error": "No data available"}), 404

        try:
            return jsonify(json.loads(latest.payload))
        except json.JSONDecodeError:
            return jsonify({"error": "Malformed JSON in payload"}), 500

    finally:
        session.close()
