import gzip
import io
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from oceanpi_ingest.api import create_app
from oceanpi_ingest.archive import ArchiveReader
from oceanpi_ingest.processors import PROCESSOR_VERSION, NmeaProcessor
from oceanpi_ingest.registry import Node, load_nodes
from oceanpi_ingest.store import LeaseLost, Store, measurements, metadata
from oceanpi_ingest.worker import Worker

NODE = Node("tabor-boy/nmea-main", "tabor-boy", "nmea2000", "test-bucket", "raw/tabor-boy/")
TOKEN = "test-only-token-" + "x" * 32


def obj(etag='"revision1"', key="raw/tabor-boy/2026/10/28/220400.log.gz"):
    return dict(Key=key, ETag=etag, Size=1234, LastModified=datetime.now(timezone.utc))


def row(value=3.09, timestamp=None):
    return dict(
        node_id=NODE.node_id,
        record_number=1,
        timestamp=timestamp or time.time(),
        name="wind_speed",
        value=value,
        unit="m/s",
        reference="Apparent",
        pgn=130306,
        src=2,
        dst=255,
    )


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        url = os.environ.get(
            "TEST_DATABASE_URL", "sqlite:///" + str(Path(self.temp.name) / "test.db")
        )
        self.store = Store(url)
        if os.environ.get("TEST_DATABASE_URL"):
            # TEST_DATABASE_URL must point to an isolated disposable database.
            metadata.drop_all(self.store.engine)
        self.store.initialize()
        self.store.sync_nodes([NODE])

    def tearDown(self):
        if os.environ.get("TEST_DATABASE_URL"):
            metadata.drop_all(self.store.engine)
        self.store.engine.dispose()
        self.temp.cleanup()

    def discover(self, revision='"revision1"', processor=PROCESSOR_VERSION):
        self.store.discover(NODE, obj(revision), processor)

    def count(self):
        with self.store.engine.connect() as conn:
            return conn.scalar(select(func.count()).select_from(measurements))

    def test_discovery_and_publication_are_idempotent_across_restart(self):
        self.discover()
        self.discover()
        job = self.store.claim(PROCESSOR_VERSION)
        self.store.finish(job, [row()], 1)
        self.discover()
        self.assertIsNone(self.store.claim(PROCESSOR_VERSION))
        self.assertEqual(self.count(), 1)
        self.store.initialize()
        self.assertEqual(len(self.store.job_rows()), 1)
        self.assertEqual(self.store.job_rows()[0]["status"], "completed")

    def test_claim_is_exclusive_and_crash_lease_is_fenced(self):
        self.discover()
        now = time.time()
        first = self.store.claim(PROCESSOR_VERSION, lease_seconds=10, now=now)
        self.assertIsNone(self.store.claim(PROCESSOR_VERSION, now=now + 1))
        replacement = self.store.claim(PROCESSOR_VERSION, now=now + 11)
        with self.assertRaises(LeaseLost):
            self.store.finish(first, [row()], 1, now=now + 12)
        self.store.finish(replacement, [row()], 1, now=now + 12)
        self.assertEqual(self.count(), 1)

    def test_partial_database_failure_rolls_back_every_measurement(self):
        self.discover()
        job = self.store.claim(PROCESSOR_VERSION)

        def broken():
            for number in range(501):
                yield dict(row(), record_number=number)
            raise ValueError("bad measurement after a batch was inserted")

        with self.assertRaises(ValueError):
            self.store.finish(job, broken(), 501)
        self.assertEqual(self.count(), 0)
        self.store.fail(job, "bad recording")
        self.assertEqual(self.store.job_rows()[0]["status"], "retry")

    def test_retries_backoff_and_exhaustion(self):
        self.discover()
        now = time.time()
        first = self.store.claim(PROCESSOR_VERSION, now=now)
        self.store.fail(first, "temporary", max_attempts=2, now=now)
        self.assertIsNone(self.store.claim(PROCESSOR_VERSION, max_attempts=2, now=now + 29))
        second = self.store.claim(PROCESSOR_VERSION, max_attempts=2, now=now + 31)
        self.store.fail(second, "permanent", max_attempts=2, now=now + 32)
        self.assertIsNone(self.store.claim(PROCESSOR_VERSION, max_attempts=2, now=now + 1000))
        self.assertEqual(self.store.job_rows()[0]["status"], "failed")

    def test_final_crash_does_not_leave_a_processing_job_forever(self):
        self.discover()
        now = time.time()
        self.store.claim(PROCESSOR_VERSION, max_attempts=1, lease_seconds=1, now=now)
        self.assertIsNone(self.store.claim(PROCESSOR_VERSION, max_attempts=1, now=now + 2))
        self.assertEqual(self.store.job_rows()[0]["status"], "failed")

    def test_new_object_revision_replaces_visible_values(self):
        self.discover()
        first = self.store.claim(PROCESSOR_VERSION)
        self.store.finish(first, [row(3)], 1)
        self.discover('"revision2"')
        second = self.store.claim(PROCESSOR_VERSION)
        self.store.finish(second, [row(4)], 1)
        self.assertEqual([m["value"] for m in self.store.latest(NODE.node_id)], [4])
        self.assertEqual(self.count(), 2)  # Audit receipts retained, older revision hidden.

    def test_older_job_cannot_replace_newer_completed_version(self):
        self.discover()
        first = self.store.claim(PROCESSOR_VERSION)
        self.discover('"revision2"')
        second = self.store.claim(PROCESSOR_VERSION)
        self.store.finish(second, [row(4)], 1)
        self.store.finish(first, [row(3)], 1)
        self.assertEqual(self.store.latest(NODE.node_id)[0]["value"], 4)

    def test_revocation_prevents_claim_and_publish(self):
        self.discover()
        first = self.store.claim(PROCESSOR_VERSION)
        self.store.sync_nodes([])
        with self.assertRaises(LeaseLost):
            self.store.finish(first, [row()], 1)
        self.assertIsNone(self.store.claim(PROCESSOR_VERSION, now=time.time() + 1000))

    def test_retention_keeps_processing_receipts(self):
        self.discover()
        job = self.store.claim(PROCESSOR_VERSION)
        self.store.finish(job, [row(timestamp=time.time() - 90000)], 1)
        self.assertEqual(self.store.prune(86400), 1)
        self.discover()
        self.assertIsNone(self.store.claim(PROCESSOR_VERSION))
        self.assertEqual(self.count(), 0)

    def test_registry_conflicts_and_immutable_identity(self):
        for prefix in ("", "/", "../raw/", "raw"):
            with self.assertRaises(ValueError):
                Node("node", "vessel", "nmea", "bucket", prefix)
        altered = Node(NODE.node_id, NODE.vessel_id, NODE.node_type, NODE.bucket, "another/")
        with self.assertRaises(ValueError):
            self.store.sync_nodes([altered])
        path = Path(self.temp.name) / "registry.json"
        other = Node("tabor-boy/other", "tabor-boy", "nmea", NODE.bucket, "raw/")
        path.write_text(
            json.dumps({"schema_version": 1, "nodes": [NODE.as_dict(), other.as_dict()]})
        )
        with self.assertRaises(ValueError):
            load_nodes(path)

    def test_read_only_api_auth_paging_and_capabilities(self):
        self.discover()
        job = self.store.claim(PROCESSOR_VERSION)
        now = time.time()
        self.store.finish(job, [dict(row(timestamp=now), record_number=i) for i in range(3)], 3)
        with TestClient(create_app(self.store, TOKEN)) as client:
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/v1/nodes").status_code, 401)
            self.assertEqual(
                client.get("/v1/nodes", headers={"Authorization": "Bearer wrong"}).status_code, 401
            )
            headers = {"Authorization": "Bearer " + TOKEN}
            nodes = client.get("/v1/nodes", headers=headers).json()["nodes"]
            self.assertEqual(nodes[0]["available_measurements"], ["wind_speed"])
            self.assertEqual(client.post("/v1/nodes", headers=headers).status_code, 405)
            params = dict(
                node_id=NODE.node_id,
                since=datetime.fromtimestamp(now - 1, timezone.utc).isoformat(),
                until=datetime.fromtimestamp(now + 1, timezone.utc).isoformat(),
                limit=2,
            )
            page = client.get("/v1/measurements", params=params, headers=headers).json()
            self.assertEqual(len(page["measurements"]), 2)
            params["cursor"] = page["next_cursor"]
            final = client.get("/v1/measurements", params=params, headers=headers).json()
            self.assertEqual(len(final["measurements"]), 1)
            self.assertIsNone(final["next_cursor"])
            self.assertEqual(
                len({m["id"] for m in page["measurements"] + final["measurements"]}), 3
            )
            params["cursor"] = "nan,1"
            self.assertEqual(
                client.get("/v1/measurements", params=params, headers=headers).status_code, 422
            )

    def test_api_health_before_worker_initializes(self):
        fresh = Store("sqlite:///" + str(Path(self.temp.name) / "fresh.db"))
        with TestClient(create_app(fresh, TOKEN)) as client:
            self.assertEqual(client.get("/healthz").status_code, 503)
        fresh.engine.dispose()

    def test_r2_pagination_filter_and_revision_precondition(self):
        client = Mock()
        current = obj()
        client.get_paginator.return_value.paginate.return_value = [
            {"Contents": [current]},
            {
                "Contents": [
                    dict(current, Key="raw/tabor-boy/camera.jpg"),
                    dict(current, Key="other/file.log.gz"),
                ]
            },
        ]
        reader = ArchiveReader(client)
        worker = Worker(self.store, reader, [NODE], NmeaProcessor())
        self.assertEqual(worker.discover(full=True)[1], 0)
        self.assertEqual(len(self.store.job_rows()), 1)
        body = io.BytesIO(gzip.compress(b"frame"))
        client.get_object.return_value = {"Body": body, "ContentLength": len(body.getvalue())}
        with reader.open_object(NODE.bucket, current["Key"], current["ETag"]) as stream:
            self.assertEqual(stream.read(), b"frame")
        self.assertTrue(body.closed)
        client.get_object.assert_called_once_with(
            Bucket=NODE.bucket, Key=current["Key"], IfMatch=current["ETag"]
        )

    def test_processor_failure_is_retriable_without_partial_output(self):
        self.discover()
        client = Mock()
        body = io.BytesIO(b"not a recording")
        client.get_object.return_value = {"Body": body, "ContentLength": len(body.getvalue())}
        processor = NmeaProcessor(
            analyzer="/nonexistent/analyzer", converter="/nonexistent/converter"
        )
        self.assertTrue(Worker(self.store, ArchiveReader(client), [NODE], processor).process_one())
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.store.job_rows()[0]["status"], "retry")

    @unittest.skipUnless(
        all(
            os.environ.get(k) for k in ("TABOR_RECORDING", "CANBOAT_ANALYZER", "CANBOAT_CONVERTER")
        ),
        "Set recording and CANboat paths for full cloud pipeline regression",
    )
    def test_real_archive_through_worker_database_and_api(self):
        data = Path(os.environ["TABOR_RECORDING"]).read_bytes()
        self.discover()
        client = Mock()
        client.get_object.side_effect = lambda **kwargs: {
            "Body": io.BytesIO(data),
            "ContentLength": len(data),
        }
        processor = NmeaProcessor(os.environ["CANBOAT_ANALYZER"], os.environ["CANBOAT_CONVERTER"])
        worker = Worker(self.store, ArchiveReader(client), [NODE], processor)
        self.assertTrue(worker.process_one())
        self.assertFalse(worker.process_one())
        self.assertEqual(self.count(), 4426)
        job = self.store.job_rows()[0]
        self.assertEqual(job["message_count"], 7459)
        self.assertIn(
            "'ERROR PGN 126208 has 2 missing fields in repeating set': 54", job["diagnostics"]
        )
        with TestClient(create_app(self.store, TOKEN)) as api:
            response = api.get(
                "/v1/latest",
                params={"node_id": NODE.node_id},
                headers={"Authorization": "Bearer " + TOKEN},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["measurements"]), 12)

    @unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Postgres concurrency integration")
    def test_concurrent_workers_cannot_claim_the_same_job(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        self.discover()
        barrier = threading.Barrier(4)

        def claim():
            barrier.wait()
            return self.store.claim(PROCESSOR_VERSION)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: claim(), range(4)))
        self.assertEqual(sum(job is not None for job in results), 1)

    @unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Postgres concurrency integration")
    def test_concurrent_revision_publication_has_one_current_version(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        self.discover()
        old = self.store.claim(PROCESSOR_VERSION)
        self.discover('"new"')
        new = self.store.claim(PROCESSOR_VERSION)
        barrier = threading.Barrier(2)

        def finish(job, value):
            barrier.wait()
            self.store.finish(job, [row(value)], 1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(finish, old, 3), pool.submit(finish, new, 4)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(self.store.latest(NODE.node_id)[0]["value"], 4)
        self.assertEqual(sum(job["is_current"] for job in self.store.job_rows()), 1)

    def test_actual_s3_sdk_contract_and_streaming_body(self):
        import boto3
        from botocore.response import StreamingBody
        from botocore.stub import Stubber

        client = boto3.client(
            "s3",
            endpoint_url="https://example.invalid",
            region_name="auto",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        current = obj()
        payload = gzip.compress(b"frame")
        with Stubber(client) as stub:
            stub.add_response(
                "list_objects_v2",
                {"IsTruncated": True, "NextContinuationToken": "next", "Contents": [current]},
                {"Bucket": NODE.bucket, "Prefix": NODE.prefix},
            )
            stub.add_response(
                "list_objects_v2",
                {"IsTruncated": False},
                {"Bucket": NODE.bucket, "Prefix": NODE.prefix, "ContinuationToken": "next"},
            )
            worker = Worker(self.store, ArchiveReader(client), [NODE], NmeaProcessor())
            self.assertEqual(worker.discover(full=True), (1, 0))
            stub.add_response(
                "get_object",
                {
                    "Body": StreamingBody(io.BytesIO(payload), len(payload)),
                    "ContentLength": len(payload),
                    "ETag": current["ETag"],
                },
                {"Bucket": NODE.bucket, "Key": current["Key"], "IfMatch": current["ETag"]},
            )
            with worker.reader.open_object(NODE.bucket, current["Key"], current["ETag"]) as stream:
                self.assertEqual(stream.read(), b"frame")
            stub.assert_no_pending_responses()

    def test_expansion_limit_rejects_archive_before_external_tools(self):
        from oceanpi_ingest.decoder import DecodeError, decode

        with self.assertRaisesRegex(DecodeError, "decompressed size limit"):
            list(decode(io.BytesIO(b"oversize"), "candump", "node", "archive", max_input_bytes=2))

    @unittest.skipUnless(
        all(os.environ.get(k) for k in ("CANBOAT_ANALYZER", "CANBOAT_CONVERTER")),
        "Set CANboat executable paths",
    )
    def test_synthetic_archive_through_worker(self):
        import struct

        data = struct.pack("<ii", 415000000, -707000000)
        payload = gzip.compress(("(1793225040.019589) can0 09F80107#" + data.hex() + "\n").encode())
        self.discover()
        client = Mock()
        client.get_object.return_value = {
            "Body": io.BytesIO(payload),
            "ContentLength": len(payload),
        }
        processor = NmeaProcessor(os.environ["CANBOAT_ANALYZER"], os.environ["CANBOAT_CONVERTER"])
        self.assertTrue(Worker(self.store, ArchiveReader(client), [NODE], processor).process_one())
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.store.job_rows()[0]["status"], "completed")
