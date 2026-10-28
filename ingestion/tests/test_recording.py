"""Opt-in regression against the user-supplied archive, without committing it."""

import hashlib
import os
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path

from oceanpi_ingest.archive import ArchiveReader
from oceanpi_ingest.decoder import decode
from oceanpi_ingest.measurements import extract


@unittest.skipUnless(
    all(
        os.environ.get(key) for key in ("TABOR_RECORDING", "CANBOAT_ANALYZER", "CANBOAT_CONVERTER")
    ),
    "Set recording and CANboat executable paths for real archive regression",
)
class RecordingTests(unittest.TestCase):
    def test_tabor_boy_2026_10_28(self):
        recording = Path(os.environ["TABOR_RECORDING"])
        self.assertEqual(
            hashlib.sha256(recording.read_bytes()).hexdigest(),
            "933b1375912a72fc01f7089f1b9763878b73e296b624afc232cc85cae7d9ca75",
        )
        with ArchiveReader().open(str(recording)) as stream:
            records = list(
                decode(
                    stream,
                    "candump",
                    "tabor-boy/nmea-main",
                    str(recording),
                    os.environ["CANBOAT_ANALYZER"],
                    os.environ["CANBOAT_CONVERTER"],
                )
            )
        self.assertEqual(len(records), 7459)
        counts = Counter(r["message"]["pgn"] for r in records)
        self.assertEqual(len(counts), 43)
        for pgn, count in {129025: 600, 129029: 60, 127250: 600, 128267: 50, 130306: 123}.items():
            self.assertEqual(counts[pgn], count)
        measurements = [m for r in records for m in extract(r)]
        self.assertEqual(len(measurements), 4426)
        first = records[0]["message"]
        self.assertTrue(40 < first["fields"]["Latitude"] < 43)
        self.assertTrue(-73 < first["fields"]["Longitude"] < -69)
        for record in records:
            timestamp = datetime.fromisoformat(
                record["message"]["timestamp"].replace("Z", "+00:00")
            )
            self.assertEqual(timestamp.isoformat()[:16], "2026-10-28T22:04")
        winds = [m for m in measurements if m["measurement"] == "wind_speed"]
        self.assertEqual(len(winds), 123)
        self.assertTrue(all(m["reference"] == "Apparent" and m["unit"] == "m/s" for m in winds))
        self.assertEqual(
            (min(m["value"] for m in winds), max(m["value"] for m in winds)), (3.09, 4.12)
        )
