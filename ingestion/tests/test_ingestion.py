import gzip
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from oceanpi_ingest.archive import ArchiveReader
from oceanpi_ingest.decoder import DecodeError, decode

MSG = dict(
    timestamp="2026-10-28T12:00:00Z", pgn=130306, src=12, dst=255, fields={"Wind Speed": 5.2}
)


class Tests(unittest.TestCase):
    def test_r2_plain_and_gzip(self):
        for payload in (b"hello", gzip.compress(b"hello")):
            client = Mock()
            body = io.BytesIO(payload)
            client.get_object.return_value = {"Body": body}
            with ArchiveReader(client).open("r2://bucket/raw/tabor-boy/log.gz") as f:
                self.assertEqual(f.read(), b"hello")
            self.assertTrue(body.closed)
            client.get_object.assert_called_once_with(Bucket="bucket", Key="raw/tabor-boy/log.gz")

    def test_listing(self):
        client = Mock()
        client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "raw/a"}, {"Key": "raw/"}]},
            {},
            {"Contents": [{"Key": "raw/b"}]},
        ]
        self.assertEqual(
            list(ArchiveReader(client).list_keys("bucket", "raw/")), ["raw/a", "raw/b"]
        )
        with self.assertRaises(ValueError):
            list(ArchiveReader(client).list_keys("bucket", ""))

    def test_wrapped_and_bare(self):
        for record in (MSG, dict(received_utc="original", source="wonder_nmea2000", message=MSG)):
            data = io.BytesIO(
                (json.dumps({"version": "test"}) + "\n" + json.dumps(record)).encode()
            )
            result = list(decode(data, "jsonl", "tabor-boy/nmea-main", "archive"))
            self.assertEqual(result[0]["message"], MSG)
            self.assertEqual(result[0]["record_number"], 2)

    def test_bad_records(self):
        for value in ("bad", "[]", "{}", json.dumps(dict(MSG, pgn=True))):
            with self.assertRaisesRegex(DecodeError, "archive: line 1"):
                list(decode(io.BytesIO(value.encode()), "jsonl", "node", "archive"))

    def test_cli_atomic_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "input"
            target = Path(d) / "output"
            source.write_text(json.dumps(MSG) + "\nbad\n")
            command = [
                sys.executable,
                "-m",
                "oceanpi_ingest",
                str(source),
                "--node-id",
                "node",
                "--format",
                "jsonl",
                "--output",
                str(target),
            ]
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(d).iterdir()), [source])
            source.write_text(json.dumps(MSG))
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            original = target.read_bytes()
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            self.assertEqual(target.read_bytes(), original)

    def test_missing_decoder(self):
        with self.assertRaisesRegex(DecodeError, "Cannot run"):
            list(
                decode(
                    io.BytesIO(b"raw"),
                    "canboat",
                    "node",
                    "archive",
                    analyzer="/nonexistent/analyzer",
                )
            )

    @unittest.skipUnless(os.environ.get("CANBOAT_ANALYZER"), "Set CANBOAT_ANALYZER for integration")
    def test_real_decoder(self):
        data = struct.pack("<ii", 415000000, -707000000)
        frame = (
            "2026-10-28T12:00:00.000Z,2,129025,12,255,8,"
            + ",".join(f"{b:02x}" for b in data)
            + "\n"
        )
        result = list(
            decode(
                io.BytesIO(frame.encode()),
                "canboat",
                "node",
                "synthetic",
                analyzer=os.environ["CANBOAT_ANALYZER"],
            )
        )
        self.assertAlmostEqual(result[0]["message"]["fields"]["Latitude"], 41.5)
        self.assertAlmostEqual(result[0]["message"]["fields"]["Longitude"], -70.7)


if __name__ == "__main__":
    unittest.main()
