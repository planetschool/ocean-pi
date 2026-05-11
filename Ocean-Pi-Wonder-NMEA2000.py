#!/usr/bin/env python3

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt


# ============================================================
# Ocean Pi - Wonder NMEA 2000 Collector
#
# Data path:
# candump can0
#   -> candump2analyzer
#   -> analyzer -json
#   -> Python
#   -> local logs + MQTT
# ============================================================


# -----------------------------
# Configuration
# -----------------------------

CAN_INTERFACE = "can0"

CANBOAT_DIR = "/home/planetschool/canboat"
CANDUMP2ANALYZER = f"{CANBOAT_DIR}/rel/linux-aarch64/candump2analyzer"
ANALYZER = f"{CANBOAT_DIR}/rel/linux-aarch64/analyzer"

LOG_DIR = Path("/home/planetschool/ocean-pi/nmea2000-logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

RAW_JSONL_LOG = LOG_DIR / "wonder_nmea2000_all.jsonl"
LATEST_JSON_FILE = LOG_DIR / "wonder_nmea2000_latest.json"
SUMMARY_JSON_FILE = LOG_DIR / "wonder_nmea2000_summary.json"

MQTT_ENABLED = True
MQTT_HOST = "323f203e3f1d4829b83bb41f5c6d6f58.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_TOPIC_ALL = "oceanpi/wonder/nmea2000/all"
MQTT_TOPIC_SUMMARY = "oceanpi/wonder/nmea2000/summary"
MQTT_USERNAME = "planetschool"
MQTT_PASSWORD = "Planetschool1"

SUMMARY_PUBLISH_INTERVAL = 2.0  # seconds

PRINT_ALL_MESSAGES = False
PRINT_SUMMARY = True


# -----------------------------
# Global state
# -----------------------------

latest_values = {}
last_summary_publish = 0
running = True


# -----------------------------
# Utility functions
# -----------------------------

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def append_jsonl(path, data):
    with open(path, "a") as f:
        f.write(json.dumps(data) + "\n")


def signal_handler(sig, frame):
    global running
    print("\nStopping NMEA 2000 collector...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# -----------------------------
# MQTT setup
# -----------------------------

mqtt_client = None

def setup_mqtt():
    global mqtt_client

    if not MQTT_ENABLED:
        return

    try:
        mqtt_client = mqtt.Client()
        mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        mqtt_client.tls_set()
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"MQTT connected to {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        print(f"[WARNING] MQTT connection failed: {e}")
        mqtt_client = None


def publish(topic, payload):
    if mqtt_client is None:
        return

    try:
        mqtt_client.publish(topic, json.dumps(payload))
    except Exception as e:
        print(f"[WARNING] MQTT publish failed: {e}")


# -----------------------------
# NMEA 2000 message mapping
# -----------------------------

def get_field(fields, *possible_names):
    """
    CANboat field names vary by PGN and device.
    This helper searches for several possible field names.
    """
    if not isinstance(fields, dict):
        return None

    for name in possible_names:
        if name in fields:
            return fields[name]

    return None


def update_latest_values(message):
    """
    Promote useful NMEA 2000 PGNs into clean dashboard fields.
    Full raw messages are still logged separately.
    """

    pgn = message.get("pgn")
    description = message.get("description", "")
    fields = message.get("fields", {})

    latest_values["last_nmea2000_update_utc"] = utc_now()

    # --------------------------------------------------------
    # PGN 129025 - Position, Rapid Update
    # --------------------------------------------------------
    if pgn == 129025:
        lat = get_field(fields, "Latitude")
        lon = get_field(fields, "Longitude")

        if lat is not None:
            latest_values["gps_latitude"] = safe_float(lat)

        if lon is not None:
            latest_values["gps_longitude"] = safe_float(lon)

    # --------------------------------------------------------
    # PGN 129026 - COG & SOG, Rapid Update
    # --------------------------------------------------------
    elif pgn == 129026:
        cog = get_field(fields, "COG", "Course Over Ground")
        sog = get_field(fields, "SOG", "Speed Over Ground")

        if cog is not None:
            latest_values["course_over_ground"] = safe_float(cog)

        if sog is not None:
            latest_values["speed_over_ground"] = safe_float(sog)

    # --------------------------------------------------------
    # PGN 127250 - Vessel Heading
    # --------------------------------------------------------
    elif pgn == 127250:
        heading = get_field(fields, "Heading")
        deviation = get_field(fields, "Deviation")
        variation = get_field(fields, "Variation")
        reference = get_field(fields, "Reference")

        if heading is not None:
            latest_values["heading"] = safe_float(heading)

        if deviation is not None:
            latest_values["heading_deviation"] = safe_float(deviation)

        if variation is not None:
            latest_values["heading_variation"] = safe_float(variation)

        if reference is not None:
            latest_values["heading_reference"] = reference

    # --------------------------------------------------------
    # PGN 128267 - Water Depth
    # --------------------------------------------------------
    elif pgn == 128267:
        depth = get_field(fields, "Depth", "Water Depth")
        offset = get_field(fields, "Offset")

        if depth is not None:
            latest_values["water_depth"] = safe_float(depth)

        if offset is not None:
            latest_values["water_depth_offset"] = safe_float(offset)

    # --------------------------------------------------------
    # PGN 130306 - Wind Data
    # --------------------------------------------------------
    elif pgn == 130306:
        wind_speed = get_field(fields, "Wind Speed")
        wind_angle = get_field(fields, "Wind Angle")
        reference = get_field(fields, "Reference")

        if wind_speed is not None:
            latest_values["wind_speed"] = safe_float(wind_speed)

        if wind_angle is not None:
            latest_values["wind_angle"] = safe_float(wind_angle)

        if reference is not None:
            latest_values["wind_reference"] = reference

    # --------------------------------------------------------
    # PGN 127488 - Engine Parameters, Rapid Update
    # --------------------------------------------------------
    elif pgn == 127488:
        engine_speed = get_field(fields, "Speed", "Engine Speed")
        engine_boost = get_field(fields, "Boost Pressure")
        engine_tilt = get_field(fields, "Tilt/Trim", "Tilt Trim")

        if engine_speed is not None:
            latest_values["engine_rpm"] = safe_float(engine_speed)

        if engine_boost is not None:
            latest_values["engine_boost_pressure"] = safe_float(engine_boost)

        if engine_tilt is not None:
            latest_values["engine_tilt_trim"] = safe_float(engine_tilt)

    # --------------------------------------------------------
    # PGN 127489 - Engine Parameters, Dynamic
    # --------------------------------------------------------
    elif pgn == 127489:
        oil_pressure = get_field(fields, "Oil Pressure")
        oil_temp = get_field(fields, "Oil Temperature")
        coolant_temp = get_field(fields, "Temperature", "Coolant Temperature")
        alternator_voltage = get_field(fields, "Alternator Potential", "Alternator Voltage")
        fuel_rate = get_field(fields, "Fuel Rate")

        if oil_pressure is not None:
            latest_values["engine_oil_pressure"] = safe_float(oil_pressure)

        if oil_temp is not None:
            latest_values["engine_oil_temperature"] = safe_float(oil_temp)

        if coolant_temp is not None:
            latest_values["engine_coolant_temperature"] = safe_float(coolant_temp)

        if alternator_voltage is not None:
            latest_values["engine_alternator_voltage"] = safe_float(alternator_voltage)

        if fuel_rate is not None:
            latest_values["engine_fuel_rate"] = safe_float(fuel_rate)

    # --------------------------------------------------------
    # PGN 127508 - Battery Status
    # --------------------------------------------------------
    elif pgn == 127508:
        instance = get_field(fields, "Instance", "Battery Instance")
        voltage = get_field(fields, "Battery Voltage", "Voltage")
        current = get_field(fields, "Battery Current", "Current")
        temperature = get_field(fields, "Battery Temperature", "Temperature")

        prefix = "battery"

        if instance is not None:
            prefix = f"battery_{instance}"

        if voltage is not None:
            latest_values[f"{prefix}_voltage"] = safe_float(voltage)

        if current is not None:
            latest_values[f"{prefix}_current"] = safe_float(current)

        if temperature is not None:
            latest_values[f"{prefix}_temperature"] = safe_float(temperature)

    # --------------------------------------------------------
    # PGN 130310 / 130311 / 130312 / 130316 - Environmental
    # --------------------------------------------------------
    elif pgn in [130310, 130311, 130312, 130316]:
        water_temp = get_field(fields, "Water Temperature", "Sea Temperature")
        outside_temp = get_field(fields, "Outside Ambient Air Temperature", "Outside Temperature")
        air_temp = get_field(fields, "Air Temperature")
        pressure = get_field(fields, "Atmospheric Pressure", "Pressure")
        humidity = get_field(fields, "Humidity")

        if water_temp is not None:
            latest_values["water_temperature"] = safe_float(water_temp)

        if outside_temp is not None:
            latest_values["outside_air_temperature"] = safe_float(outside_temp)

        if air_temp is not None:
            latest_values["air_temperature"] = safe_float(air_temp)

        if pressure is not None:
            latest_values["atmospheric_pressure"] = safe_float(pressure)

        if humidity is not None:
            latest_values["relative_humidity"] = safe_float(humidity)

    # --------------------------------------------------------
    # Keep a lightweight count of PGNs seen
    # --------------------------------------------------------
    pgn_key = f"pgn_{pgn}_count"
    latest_values[pgn_key] = latest_values.get(pgn_key, 0) + 1

    if description:
        latest_values[f"pgn_{pgn}_description"] = description


# -----------------------------
# Process handling
# -----------------------------

def start_pipeline():
    """
    Starts:
        candump can0
        candump2analyzer
        analyzer -json
    """

    print("Starting CANboat pipeline...")
    print(f"CAN interface: {CAN_INTERFACE}")

    candump = subprocess.Popen(
        ["candump", CAN_INTERFACE],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    converter = subprocess.Popen(
        [CANDUMP2ANALYZER],
        stdin=candump.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    analyzer = subprocess.Popen(
        [ANALYZER, "-json"],
        stdin=converter.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    return candump, converter, analyzer


def stop_pipeline(processes):
    for process in processes:
        if process and process.poll() is None:
            process.terminate()

    time.sleep(1)

    for process in processes:
        if process and process.poll() is None:
            process.kill()


# -----------------------------
# Main loop
# -----------------------------

def run():
    global last_summary_publish

    setup_mqtt()

    while running:
        processes = None

        try:
            candump, converter, analyzer = start_pipeline()
            processes = [analyzer, converter, candump]

            for line in analyzer.stdout:
                if not running:
                    break

                line = line.strip()

                if not line:
                    continue

                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[WARNING] Bad JSON: {line}")
                    continue

                # CANboat emits a version line at startup
                if "version" in message:
                    print(f"CANboat analyzer version: {message.get('version')}")
                    continue

                record = {
                    "received_utc": utc_now(),
                    "source": "wonder_nmea2000",
                    "message": message,
                }

                append_jsonl(RAW_JSONL_LOG, record)
                save_json(LATEST_JSON_FILE, record)
                publish(MQTT_TOPIC_ALL, record)

                update_latest_values(message)

                now = time.monotonic()

                if now - last_summary_publish >= SUMMARY_PUBLISH_INTERVAL:
                    summary = {
                        "timestamp_utc": utc_now(),
                        "source": "wonder_nmea2000",
                        **latest_values,
                    }

                    save_json(SUMMARY_JSON_FILE, summary)
                    publish(MQTT_TOPIC_SUMMARY, summary)

                    if PRINT_SUMMARY:
                        print(json.dumps(summary, indent=2))

                    last_summary_publish = now

                if PRINT_ALL_MESSAGES:
                    print(json.dumps(record, indent=2))

        except Exception as e:
            print(f"[ERROR] NMEA 2000 collector crashed: {e}")
            print("Restarting in 5 seconds...")
            time.sleep(5)

        finally:
            if processes:
                stop_pipeline(processes)

    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

    print("NMEA 2000 collector stopped.")


if __name__ == "__main__":
    run()
