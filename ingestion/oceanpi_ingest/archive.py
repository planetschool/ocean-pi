"""Read local or R2 objects without archive writes or implicit prefix scans."""

import gzip
import io
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class ArchiveReader:
    def __init__(self, client=None):
        self.client = client

    def list_keys(self, bucket, prefix):
        if self.client is None:
            raise ValueError("R2 client is required")
        if not prefix:
            raise ValueError("An explicit nonempty archive prefix is required")
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix
        ):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith("/"):
                    yield obj["Key"]

    @contextmanager
    def open(self, location):
        uri = urlsplit(location)
        if uri.scheme == "r2":
            if self.client is None:
                raise ValueError("R2 client is required")
            if not uri.netloc or not uri.path.lstrip("/") or uri.query or uri.fragment:
                raise ValueError("Expected r2://bucket/exact-object-key")
            raw = self.client.get_object(Bucket=uri.netloc, Key=uri.path[1:])["Body"]
        elif uri.scheme:
            raise ValueError("Only local paths and r2:// objects are supported")
        else:
            raw = Path(location).open("rb")
        try:
            # The gzip magic handles archives with or without a .gz suffix.
            with io.BufferedReader(raw) as buffered:
                if buffered.peek(2)[:2] == b"\x1f\x8b":
                    with gzip.GzipFile(fileobj=buffered) as uncompressed:
                        yield uncompressed
                else:
                    yield buffered
        finally:
            raw.close()

    @contextmanager
    def open_object(self, bucket, key, etag, max_bytes=8 * 1024 * 1024):
        """Read exactly the object revision cataloged during discovery."""
        response = self.client.get_object(Bucket=bucket, Key=key, IfMatch=etag)
        raw = response["Body"]
        try:
            if response.get("ContentLength", max_bytes + 1) > max_bytes:
                raise ValueError("Archive exceeds configured compressed size limit")
            with io.BufferedReader(raw) as buffered:
                if buffered.peek(2)[:2] == b"\x1f\x8b":
                    with gzip.GzipFile(fileobj=buffered) as uncompressed:
                        yield uncompressed
                else:
                    yield buffered
        finally:
            raw.close()


def r2_client(endpoint, profile=None):
    if not endpoint or urlsplit(endpoint).scheme != "https":
        raise ValueError("An explicit HTTPS R2 S3 endpoint is required")
    import boto3
    from botocore.config import Config

    return boto3.Session(profile_name=profile).client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=30
        ),
    )
