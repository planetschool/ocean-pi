"""Read-only dashboard API. Keep its bearer token in a server-side proxy."""

import math
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .store import Store, settings


def utc(value):
    return (
        datetime.fromtimestamp(value, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
        if value is not None
        else None
    )


def create_app(store=None, token=None):
    token = token if token is not None else os.environ.get("API_TOKEN", "")
    if len(token) < 32:
        raise ValueError("API_TOKEN must contain at least 32 characters")
    owned = store is None
    store = store or Store(os.environ["DATABASE_URL"])

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owned:
            store.engine.dispose()

    app = FastAPI(
        title="Ocean Pi ingestion API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    bearer = HTTPBearer(auto_error=False)

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(
                401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
            )

    def node_exists(node_id):
        if not any(row["node_id"] == node_id for row in store.node_rows()):
            raise HTTPException(404, "Node not found")

    def serialize_measurement(row):
        row = dict(row)
        row.pop("rank", None)
        row["timestamp_utc"] = utc(row.pop("timestamp"))
        return row

    @app.get("/healthz")
    def health():
        try:
            with store.engine.connect() as conn:
                version = conn.scalar(
                    select(settings.c.value).where(settings.c.key == "schema_version")
                )
            if version != "1":
                raise HTTPException(503, "Database initialization pending")
        except SQLAlchemyError:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ok"}

    @app.get("/v1/nodes", dependencies=[Depends(authorize)])
    def list_nodes():
        result = []
        for row in store.node_rows():
            latest = store.latest(row["node_id"])
            result.append(
                {
                    "node_id": row["node_id"],
                    "vessel_id": row["vessel_id"],
                    "node_type": row["definition"]["node_type"],
                    "approved": row["approved"],
                    "data_type": row["definition"]["data_type"],
                    "last_archive_modified_utc": utc(row["last_seen"]),
                    "available_measurements": sorted({m["name"] for m in latest}),
                    "latest_measurement_utc": utc(
                        max((m["timestamp"] for m in latest), default=None)
                    ),
                }
            )
        return {"nodes": result}

    @app.get("/v1/status", dependencies=[Depends(authorize)])
    def status():
        result = store.status()
        result["latest_completed_utc"] = utc(result.pop("latest_completed_at"))
        result["worker"] = store.worker_state()
        result["worker_stale"] = (
            result["worker"] is None or time.time() - result["worker"]["timestamp"] > 300
        )
        return result

    @app.get("/v1/objects", dependencies=[Depends(authorize)])
    def list_objects(limit: int = Query(100, ge=1, le=1000)):
        rows = store.job_rows(limit)
        for row in rows:
            row.pop("token", None)
            for name in ("modified", "completed_at", "lease_until", "next_attempt"):
                row[name] = utc(row[name])
        return {"objects": rows}

    @app.get("/v1/latest", dependencies=[Depends(authorize)])
    def latest(node_id: str):
        node_exists(node_id)
        rows = store.latest(node_id)
        result = []
        for row in rows:
            age = time.time() - row["timestamp"]
            serialized = serialize_measurement(row)
            serialized["age_seconds"] = round(age, 3)
            result.append(serialized)
        return {"node_id": node_id, "measurements": result}

    @app.get("/v1/measurements", dependencies=[Depends(authorize)])
    def history(
        node_id: str,
        since: datetime,
        until: datetime,
        name: str | None = None,
        limit: int = Query(1000, ge=1, le=10000),
        cursor: str | None = None,
    ):
        node_exists(node_id)
        if since.tzinfo is None or until.tzinfo is None:
            raise HTTPException(422, "since and until must include a timezone")
        start, end = since.timestamp(), until.timestamp()
        if not 0 <= end - start <= 86400:
            raise HTTPException(422, "Time range must be ordered and at most 24 hours")
        after = None
        if cursor:
            try:
                stamp, row_id = cursor.split(",")
                after = float(stamp), int(row_id)
                if not math.isfinite(after[0]) or after[1] < 1:
                    raise ValueError()
            except ValueError:
                raise HTTPException(422, "Invalid cursor") from None
        rows = store.measurement_rows(node_id, start, end, limit + 1, name, after)
        page = rows[:limit]
        next_cursor = f"{page[-1]['timestamp']},{page[-1]['id']}" if len(rows) > limit else None
        return {
            "measurements": [serialize_measurement(row) for row in page],
            "next_cursor": next_cursor,
        }

    return app
