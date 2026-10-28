"""Render background worker: discover, claim, decode, commit, repeat."""

import argparse
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

from .archive import ArchiveReader, r2_client
from .decoder import DecodeError
from .processors import NmeaProcessor
from .registry import load_nodes
from .store import LeaseLost, Store

log = logging.getLogger(__name__)


def safe_error(exc):
    if isinstance(exc, (DecodeError, LeaseLost, ValueError, EOFError)):
        return f"{type(exc).__name__}: {str(exc)[:1800]}"
    response = getattr(exc, "response", {})
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    return f"R2 request failed ({code})" if code else f"{type(exc).__name__}: processing failed"


class Worker:
    def __init__(
        self,
        store,
        reader,
        definitions,
        processor,
        stop=None,
        poll_seconds=30,
        reconcile_seconds=3600,
        max_jobs=20,
        max_object_bytes=8 * 1024 * 1024,
        max_attempts=5,
        retention_days=1,
    ):
        self.store = store
        self.reader = reader
        self.definitions = {node.node_id: node for node in definitions if node.approved}
        self.processor = processor
        self.stop = stop or threading.Event()
        self.poll_seconds = poll_seconds
        self.reconcile_seconds = reconcile_seconds
        self.max_jobs = max_jobs
        self.max_object_bytes = max_object_bytes
        self.max_attempts = max_attempts
        self.retention_seconds = retention_days * 86400
        self.last_full_scan = None
        self.last_prune = None

    def discover(self, full=False, now=None):
        now = time.time() if now is None else now
        node_rows = {row["node_id"]: row for row in self.store.node_rows()}
        discovered = 0
        failures = 0
        for node in self.definitions.values():
            if self.stop.is_set():
                break
            if node.data_type != self.processor.data_type:
                continue  # Registered for future processors; no speculative decoding.
            cutoff = max(node_rows[node.node_id]["discovery_start"], now - self.retention_seconds)
            prefixes = [node.prefix]
            if node.date_partitioned and not full:
                prefixes = [
                    node.prefix
                    + (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=day)).strftime(
                        "%Y/%m/%d/"
                    )
                    for day in range(2)
                ]
            try:
                for prefix in prefixes:
                    pages = self.reader.client.get_paginator("list_objects_v2").paginate(
                        Bucket=node.bucket, Prefix=prefix
                    )
                    for page in pages:
                        if self.stop.is_set():
                            return discovered, failures
                        for obj in page.get("Contents", []):
                            key = obj["Key"]
                            if not key.startswith(node.prefix) or not key.endswith(
                                (".log", ".log.gz", ".raw", ".raw.gz")
                            ):
                                continue
                            if not obj.get("ETag") or obj["LastModified"].timestamp() < cutoff:
                                continue
                            if not 0 < obj["Size"] <= self.max_object_bytes:
                                log.warning(
                                    "Archive skipped for size: node=%s key=%s", node.node_id, key
                                )
                                continue
                            self.store.discover(node, obj, self.processor.version)
                            discovered += 1
            except Exception as exc:
                failures += 1
                # Credentials and connection URLs never belong in service logs.
                log.error("Archive discovery failed for %s: %s", node.node_id, safe_error(exc))
        return discovered, failures

    def process_one(self):
        # Lease covers both external tool deadlines plus bounded database publication.
        job = self.store.claim(
            self.processor.version,
            lease_seconds=2 * self.processor.timeout + 300,
            max_attempts=self.max_attempts,
        )
        if not job:
            return False
        node = self.definitions.get(job["node_id"])
        try:
            if node is None or node.data_type != self.processor.data_type:
                raise ValueError("Node is not approved for this processor")
            with self.reader.open_object(
                job["bucket"], job["key"], job["etag"], self.max_object_bytes
            ) as stream:
                self.processor.process(
                    stream,
                    node,
                    job,
                    lambda result: self.store.finish(
                        job, result.rows, result.message_count, result.diagnostics
                    ),
                )
            log.info("Archive completed: id=%s node=%s", job["id"], node.node_id)
        except Exception as exc:
            # Preserve decoder details while excluding credentials/connection URLs.
            self.store.fail(
                job,
                safe_error(exc),
                self.max_attempts,
            )
            log.error("Archive failed: id=%s %s", job["id"], safe_error(exc))
        return True

    def tick(self):
        now = time.time()
        full = self.last_full_scan is None or now - self.last_full_scan >= self.reconcile_seconds
        seen, failures = self.discover(full=full, now=now)
        if full and not failures:
            self.last_full_scan = now
        processed = 0
        while not self.stop.is_set() and processed < self.max_jobs and self.process_one():
            processed += 1
        if self.last_prune is None or now - self.last_prune >= 3600:
            self.store.prune(self.retention_seconds, now)
            self.last_prune = now
        self.store.heartbeat(
            {
                "timestamp": time.time(),
                "discovery_failures": failures,
                "objects_seen": seen,
                "jobs_attempted": processed,
            }
        )
        return processed

    def run(self, once=False):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                log.error("Worker cycle failed (%s)", type(exc).__name__)
            if once:
                return
            self.stop.wait(self.poll_seconds)


def positive_env(name, default, maximum):
    value = int(os.environ.get(name, default))
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Perform one bounded worker cycle")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Verify the decoder matches the version in processing identities.
    import subprocess

    analyzer = os.environ.get("CANBOAT_ANALYZER", "analyzer")
    converter = os.environ.get("CANBOAT_CONVERTER", "candump2analyzer")
    if subprocess.check_output([analyzer, "-version"], text=True, timeout=10).strip() != "9.1.0":
        raise ValueError("Worker requires pinned CANboat 9.1.0")
    definitions = load_nodes(os.environ.get("NODE_REGISTRY_PATH"), os.environ.get("R2_BUCKET"))
    store = Store(os.environ["DATABASE_URL"])
    store.initialize()
    store.sync_nodes(
        definitions, initial_lookback=positive_env("INITIAL_LOOKBACK_SECONDS", 3600, 31536000)
    )
    reader = ArchiveReader(r2_client(os.environ["R2_ENDPOINT_URL"]))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    worker = Worker(
        store,
        reader,
        definitions,
        NmeaProcessor(analyzer, converter),
        stop,
        poll_seconds=positive_env("POLL_SECONDS", 30, 3600),
        reconcile_seconds=positive_env("RECONCILE_SECONDS", 3600, 86400),
        max_jobs=positive_env("MAX_JOBS_PER_CYCLE", 20, 1000),
        retention_days=positive_env("MEASUREMENT_RETENTION_DAYS", 1, 365),
    )
    worker.run(once=args.once)


if __name__ == "__main__":
    main()
