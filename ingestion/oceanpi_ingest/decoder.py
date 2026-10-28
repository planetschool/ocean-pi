"""CANboat-backed decoding with original fields, units and timestamps intact."""

import json
import logging
import re
import subprocess
import tempfile
from collections import Counter


class DecodeError(ValueError):
    pass


def normalize(lines, node_id, archive_uri):
    if not node_id or not node_id.strip():
        raise ValueError("An explicit node ID is required")
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("record must be an object")
            if "version" in record and "pgn" not in record:
                continue  # CANboat's stream header
            message = record.get("message", record)
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            pgn = message.get("pgn")
            if type(pgn) is not int or not 0 <= pgn <= 0x3FFFF:
                raise ValueError("invalid or missing PGN")
            for field in ("src", "dst"):
                if type(message.get(field)) is not int or not 0 <= message[field] <= 255:
                    raise ValueError(f"invalid or missing {field}")
            if not isinstance(message.get("timestamp"), str) or not message["timestamp"]:
                raise ValueError("missing message timestamp")
            if not isinstance(message.get("fields", {}), dict):
                raise ValueError("fields must be an object")
        except (ValueError, TypeError) as exc:
            raise DecodeError(f"{archive_uri}: line {number}: {exc}") from exc
        yield {
            "schema_version": 1,
            "node_id": node_id,
            "archive_uri": archive_uri,
            "record_number": number,
            "received_utc": record.get("received_utc"),
            "source": record.get("source"),
            "message": message,
        }


def _run(command, source, target, timeout):
    # Disk-backed stderr prevents a blocked pipe and bounds memory for long logs.
    with tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(
                command, stdin=source, stdout=target, stderr=errors, timeout=timeout, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DecodeError(f"Cannot run {command[0]}: {exc}") from exc
        if result.returncode:
            errors.seek(0)
            detail = errors.read(4096).decode("utf-8", errors="replace")
            raise DecodeError(f"{command[0]} failed ({result.returncode}): {detail}")
        errors.seek(0)
        diagnostic_counts = Counter()
        for line in errors:
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                # Aggregate repeated errors without losing their total counts.
                text = re.sub(r"^(\w+) \S+ \[[^]]+\] ", r"\1 ", text)
                diagnostic_counts[text[:1024]] += 1
                if len(diagnostic_counts) > 100:
                    diagnostic_counts["Additional distinct diagnostics (truncated)"] += (
                        diagnostic_counts.pop(text[:1024])
                    )
        if diagnostic_counts:
            logging.getLogger(__name__).warning(
                "%s diagnostics: %s", command[0], dict(diagnostic_counts)
            )
    target.seek(0)


def decode(
    stream,
    input_format,
    node_id,
    archive_uri,
    analyzer="analyzer",
    converter="candump2analyzer",
    timeout=300,
    max_input_bytes=None,
):
    if input_format == "jsonl":
        yield from normalize(stream, node_id, archive_uri)
        return
    if input_format not in ("candump", "canboat"):
        raise ValueError("Unsupported recording format")
    # Spool once: gzip and R2 bodies have no subprocess-compatible descriptor.
    # Keep all frames together so CANboat can reassemble fast packets.
    with (
        tempfile.TemporaryFile() as raw,
        tempfile.TemporaryFile() as converted,
        tempfile.TemporaryFile() as decoded,
    ):
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if max_input_bytes is not None and total > max_input_bytes:
                raise DecodeError("Archive exceeds configured decompressed size limit")
            raw.write(chunk)
        raw.seek(0)
        source = raw
        if input_format == "candump":
            _run([converter], raw, converted, timeout)
            source = converted
        _run([analyzer, "-json"], source, decoded, timeout)
        count = 0
        for record in normalize(decoded, node_id, archive_uri):
            count += 1
            yield record
        if not count:
            raise DecodeError(f"{archive_uri}: CANboat produced no decoded messages")
