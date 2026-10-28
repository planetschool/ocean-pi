import math
import unittest

from oceanpi_ingest.measurements import extract


def record(pgn, fields, timestamp="2026-10-28T18:04:00-04:00"):
    return dict(
        node_id="test/node",
        archive_uri="fixture",
        record_number=1,
        message=dict(pgn=pgn, fields=fields, timestamp=timestamp, src=2, dst=255),
    )


class MeasurementTests(unittest.TestCase):
    def test_units_reference_and_utc(self):
        values = list(
            extract(
                record(130306, {"Wind Speed": 3.09, "Wind Angle": 197.0, "Reference": "Apparent"})
            )
        )
        self.assertEqual(
            [(m["measurement"], m["value"], m["unit"]) for m in values],
            [("wind_speed", 3.09, "m/s"), ("wind_angle", 197.0, "deg")],
        )
        self.assertTrue(all(m["reference"] == "Apparent" for m in values))
        self.assertTrue(all(m["timestamp_utc"] == "2026-10-28T22:04:00.000Z" for m in values))
        self.assertEqual(values[0]["src"], 2)

    def test_missing_and_invalid_values_are_not_zero(self):
        for value in (None, True, "Unknown", math.nan, math.inf):
            self.assertEqual(list(extract(record(130306, {"Wind Speed": value}))), [])
        self.assertEqual(list(extract(record(130306, {"Wind Speed": 0})))[0]["value"], 0)

    def test_depth_preserves_datum(self):
        values = list(extract(record(128267, {"Depth": 1.92, "Offset": -0.5})))
        self.assertEqual(values[0]["measurement"], "depth_below_transducer")
        self.assertEqual(values[0]["value"], 1.92)
        self.assertEqual(values[1]["value"], -0.5)

    def test_coordinates_and_timezone_are_validated(self):
        with self.assertRaises(ValueError):
            list(extract(record(129025, {"Latitude": 91})))
        with self.assertRaises(ValueError):
            list(extract(record(129025, {"Longitude": 181})))
        with self.assertRaises(ValueError):
            list(extract(record(129025, {}, "2026-10-28T18:00:00")))

    def test_unknown_pgn_has_no_invented_measurements(self):
        self.assertEqual(list(extract(record(130845, {"Value": 42}))), [])
