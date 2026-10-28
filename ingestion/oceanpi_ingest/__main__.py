import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

from .archive import ArchiveReader, r2_client
from .decoder import decode


def main():
    parser = argparse.ArgumentParser(description="Read-only offline NMEA 2000 ingestion")
    parser.add_argument("recording", help="Local path or r2://bucket/exact-key")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--format", required=True, choices=["candump", "canboat", "jsonl"])
    parser.add_argument("--output", required=True, type=Path, help="New local JSONL file")
    parser.add_argument("--endpoint", default=os.environ.get("R2_ENDPOINT_URL"))
    parser.add_argument("--profile")
    parser.add_argument("--analyzer", default="analyzer")
    parser.add_argument("--converter", default="candump2analyzer")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    temp_name = None
    try:
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        client = (
            r2_client(args.endpoint, args.profile) if args.recording.startswith("r2://") else None
        )
        counts = Counter()
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=args.output.parent, delete=False
        ) as target:
            temp_name = target.name
            with ArchiveReader(client).open(args.recording) as stream:
                for record in decode(
                    stream,
                    args.format,
                    args.node_id,
                    args.recording,
                    args.analyzer,
                    args.converter,
                    args.timeout,
                ):
                    target.write(json.dumps(record, allow_nan=False) + "\n")
                    counts[record["message"]["pgn"]] += 1
        if not counts:
            raise ValueError("Recording contained no messages")
        # Publish only a complete successful run, without overwriting any file.
        os.link(temp_name, args.output)
        print(
            json.dumps(
                {"messages": sum(counts.values()), "pgn_counts": counts, "output": str(args.output)}
            )
        )
    except (ValueError, OSError, ImportError) as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
