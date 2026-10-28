"""Selected measurements from CANboat's default metric/degree JSON output.

Do not use on JSON produced with -si or custom unit settings. Unknown PGNs and
fields remain in the decoded archive and are not guessed into measurements.
"""

import math
from datetime import datetime, timezone

# PGN: field, measurement name, unit. References remain separate qualifiers.
FIELDS = {
    129025: [("Latitude", "latitude", "deg"), ("Longitude", "longitude", "deg")],
    127250: [("Heading", "heading", "deg")],
    128267: [("Depth", "depth_below_transducer", "m"), ("Offset", "depth_offset", "m")],
    130306: [("Wind Speed", "wind_speed", "m/s"), ("Wind Angle", "wind_angle", "deg")],
    127257: [("Yaw", "yaw", "deg"), ("Pitch", "pitch", "deg"), ("Roll", "roll", "deg")],
    129026: [("COG", "course_over_ground", "deg"), ("SOG", "speed_over_ground", "m/s")],
}


def extract(record):
    message = record["message"]
    fields = message.get("fields", {})
    timestamp = datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Measurement timestamp must include a timezone")
    timestamp = (
        timestamp.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
    for field, name, unit in FIELDS.get(message["pgn"], []):
        value = fields.get(field)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            continue  # Missing/unavailable data must not become zero.
        if name == "latitude" and not -90 <= value <= 90:
            raise ValueError("Latitude out of range")
        if name == "longitude" and not -180 <= value <= 180:
            raise ValueError("Longitude out of range")
        yield {
            "schema_version": 1,
            "node_id": record["node_id"],
            "archive_uri": record["archive_uri"],
            "record_number": record["record_number"],
            "timestamp_utc": timestamp,
            "pgn": message["pgn"],
            "src": message["src"],
            "dst": message["dst"],
            "measurement": name,
            "value": value,
            "unit": unit,
            "reference": fields.get("Reference", fields.get("COG Reference")),
        }
