"""Replay one local archive and save a reproducible first-stage QA report."""

import argparse
import gzip
import hashlib
import io
import json
import logging
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from oceanpi_ingest.archive import ArchiveReader
from oceanpi_ingest.decoder import decode
from oceanpi_ingest.measurements import extract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--analyzer", required=True)
    parser.add_argument("--converter", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--node-id", default="tabor-boy/nmea-main")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    data = args.recording.read_bytes()
    raw = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
    frames = raw.decode("utf-8").splitlines()
    raw_counts = Counter()
    raw_times = []
    for number, line in enumerate(frames, 1):
        match = re.fullmatch(r"\((\d+\.\d+)\)\s+\S+\s+([0-9A-Fa-f]{8})#([0-9A-Fa-f]{0,16})", line)
        if not match or len(match[3]) % 2:
            raise ValueError(f"Invalid classic candump frame at line {number}")
        can_id = int(match[2], 16)
        pgn = (can_id >> 8) & 0x3FFFF
        if (pgn & 0xFF00) < 0xF000:
            pgn &= 0x3FF00
        raw_counts[pgn] += 1
        raw_times.append(float(match[1]))
    diagnostics = io.StringIO()
    handler = logging.StreamHandler(diagnostics)
    logger = logging.getLogger("oceanpi_ingest.decoder")
    logger.addHandler(handler)
    start = time.perf_counter()
    try:
        with ArchiveReader().open(str(args.recording)) as stream:
            records = list(
                decode(
                    stream,
                    "candump",
                    args.node_id,
                    str(args.recording),
                    args.analyzer,
                    args.converter,
                )
            )
    finally:
        logger.removeHandler(handler)
    elapsed = time.perf_counter() - start
    messages = [r["message"] for r in records]
    times = [datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00")) for m in messages]
    if any(t.tzinfo is None for t in times):
        raise ValueError("Timezone missing")
    decoded = "".join(json.dumps(r, allow_nan=False) + "\n" for r in records)
    # A second independent replay verifies that IDs, timestamps and fields are stable.
    with ArchiveReader().open(str(args.recording)) as stream:
        replay = "".join(
            json.dumps(r, allow_nan=False) + "\n"
            for r in decode(
                stream, "candump", args.node_id, str(args.recording), args.analyzer, args.converter
            )
        )
    if replay != decoded:
        raise ValueError("Replay differs")
    measurements = [m for r in records for m in extract(r)]
    ranges = defaultdict(list)
    for m in measurements:
        ranges[(m["measurement"], m["unit"], m["reference"])].append(m["value"])
    counts = Counter(m["pgn"] for m in messages)
    report = {
        "recording": str(args.recording),
        "compressed_sha256": hashlib.sha256(data).hexdigest(),
        "compressed_bytes": len(data),
        "uncompressed_bytes": len(raw),
        "raw_frames": len(frames),
        "raw_start_utc": datetime.fromtimestamp(min(raw_times), timezone.utc).isoformat(),
        "raw_end_utc": datetime.fromtimestamp(max(raw_times), timezone.utc).isoformat(),
        "decoded_messages": len(records),
        "distinct_pgns": len(counts),
        "decoded_start_utc": min(times).isoformat(),
        "decoded_end_utc": max(times).isoformat(),
        "timestamp_regressions": sum(b < a for a, b in zip(times, times[1:])),
        "processing_seconds": elapsed,
        "deterministic_replay": True,
        "analyzer_version": subprocess.check_output([args.analyzer, "-version"], text=True).strip(),
        "decoder_diagnostics": diagnostics.getvalue(),
        "pgn_counts": dict(sorted(counts.items())),
        "raw_frame_counts": dict(sorted(raw_counts.items())),
        "measurement_count": len(measurements),
        "measurement_ranges": [
            dict(
                measurement=k[0],
                unit=k[1],
                reference=k[2],
                count=len(v),
                minimum=min(v),
                maximum=max(v),
            )
            for k, v in ranges.items()
        ],
        "limitations": [
            "Local download tested; authenticated R2 access not tested.",
            "CANboat message counts differ from frames because fast packets span frames.",
            "No independent instrument comparison; plausible decoded values are not calibrated truth.",
            "Node ID is an explicit replay label; no registry or vessel identity inferred from CAN.",
        ],
    }
    (args.output_dir / "decoded.jsonl").write_text(decoded)
    (args.output_dir / "measurements.jsonl").write_text(
        "".join(json.dumps(m) + "\n" for m in measurements)
    )
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
