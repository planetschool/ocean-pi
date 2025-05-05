import os
from datetime import datetime
from flask import Flask, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import paho.mqtt.client as mqtt

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configure database connection
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Define MQTTMessage model
class MQTTMessage(Base):
    __tablename__ = "mqtt_messages"
    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String(255), nullable=False)
    payload = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Create database tables
Base.metadata.create_all(bind=engine)

# MQTT client setup
MQTT_BROKER = os.environ.get("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
MQTT_TOPICS = os.environ.get("MQTT_TOPICS", "#")  # Subscribe to all topics by default

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT Broker")
        client.subscribe(MQTT_TOPICS)
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    session = SessionLocal()
    try:
        message = MQTTMessage(topic=msg.topic, payload=msg.payload.decode())
        session.add(message)
        session.commit()
    except Exception as e:
        print(f"Error saving message: {e}")
        session.rollback()
    finally:
        session.close()

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()

# API endpoint to retrieve messages
@app.route("/api/messages", methods=["GET"])
def get_messages():
    session = SessionLocal()
    try:
        messages = session.query(MQTTMessage).order_by(MQTTMessage.timestamp.desc()).limit(100).all()
        return jsonify([
            {
                "id": msg.id,
                "topic": msg.topic,
                "payload": msg.payload,
                "timestamp": msg.timestamp.isoformat()
            } for msg in messages
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# Run the app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
