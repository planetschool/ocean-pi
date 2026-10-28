"""Processor interface; only NMEA 2000 is implemented in this increment."""

import io
import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from .decoder import decode
from .measurements import extract

# Bump whenever decoding or extraction changes; this becomes part of archive identity.
PROCESSOR_VERSION = "nmea2000-v1-canboat9.1.0"


@dataclass
class Processed:
    rows: object
    message_count: int
    diagnostics: str


class NmeaProcessor:
    version = PROCESSOR_VERSION
    data_type = "nmea2000.raw"

    def __init__(
        self,
        analyzer="analyzer",
        converter="candump2analyzer",
        timeout=300,
        max_input_bytes=16 * 1024 * 1024,
    ):
        self.analyzer = analyzer
        self.converter = converter
        self.timeout = timeout
        self.max_input_bytes = max_input_bytes

    def process(self, stream, node, job, consume):
        uri = f"r2://{job['bucket']}/{quote(job['key'], safe='/')}"
        capture = io.StringIO()
        handler = logging.StreamHandler(capture)
        logger = logging.getLogger("oceanpi_ingest.decoder")
        logger.addHandler(handler)
        count = 0
        try:
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as staged:
                for record in decode(
                    stream,
                    node.input_format,
                    node.node_id,
                    uri,
                    self.analyzer,
                    self.converter,
                    self.timeout,
                    self.max_input_bytes,
                ):
                    count += 1
                    for measurement in extract(record):
                        row = dict(
                            node_id=node.node_id,
                            record_number=measurement["record_number"],
                            timestamp=datetime.fromisoformat(
                                measurement["timestamp_utc"].replace("Z", "+00:00")
                            ).timestamp(),
                            name=measurement["measurement"],
                            value=measurement["value"],
                            unit=measurement["unit"],
                            reference=measurement["reference"],
                            pgn=measurement["pgn"],
                            src=measurement["src"],
                            dst=measurement["dst"],
                        )
                        staged.write(json.dumps(row, allow_nan=False) + "\n")
                if not count:
                    raise ValueError("Archive contained no decoded messages")
                staged.seek(0)
                consume(Processed((json.loads(line) for line in staged), count, capture.getvalue()))
        finally:
            logger.removeHandler(handler)
