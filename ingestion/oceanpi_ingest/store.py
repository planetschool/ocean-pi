"""Durable catalog with atomic claims and fenced, transactional publication."""

import hashlib
import json
import time
import uuid
from collections.abc import Iterable

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = MetaData()
settings = Table(
    "oceanpi_settings",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("value", Text, nullable=False),
)
nodes = Table(
    "oceanpi_nodes",
    metadata,
    Column("node_id", String(128), primary_key=True),
    Column("vessel_id", String(128), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("approved", Boolean, nullable=False),
    Column("discovery_start", Float, nullable=False),
    Column("last_seen", Float),
)
objects = Table(
    "oceanpi_objects",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fingerprint", String(64), unique=True, nullable=False),
    Column("node_id", ForeignKey(nodes.c.node_id), nullable=False),
    Column("bucket", String(255), nullable=False),
    Column("key", Text, nullable=False),
    Column("etag", String(255), nullable=False),
    Column("size", Integer, nullable=False),
    Column("modified", Float, nullable=False),
    Column("processor", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("next_attempt", Float, nullable=False, default=0),
    Column("lease_until", Float),
    Column("token", String(36)),
    Column("error", Text),
    Column("diagnostics", Text),
    Column("message_count", Integer),
    Column("measurement_count", Integer),
    Column("completed_at", Float),
    Column("is_current", Boolean, nullable=False, default=False),
)
measurements = Table(
    "oceanpi_measurements",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("object_id", ForeignKey(objects.c.id, ondelete="CASCADE"), nullable=False),
    Column("node_id", String(128), nullable=False),
    Column("record_number", Integer, nullable=False),
    Column("timestamp", Float, nullable=False),
    Column("name", String(128), nullable=False),
    Column("value", Float, nullable=False),
    Column("unit", String(32), nullable=False),
    Column("reference", String(128)),
    Column("pgn", Integer, nullable=False),
    Column("src", Integer, nullable=False),
    Column("dst", Integer, nullable=False),
    UniqueConstraint("object_id", "record_number", "name"),
)
Index("oceanpi_jobs_ready", objects.c.status, objects.c.next_attempt)
Index("oceanpi_object_key", objects.c.node_id, objects.c.bucket, objects.c.key)
Index(
    "oceanpi_measurement_lookup",
    measurements.c.node_id,
    measurements.c.name,
    measurements.c.timestamp,
)


class LeaseLost(RuntimeError):
    pass


class Store:
    def __init__(self, url):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        if self.engine.dialect.name not in ("sqlite", "postgresql"):
            raise ValueError("Only PostgreSQL and local SQLite are supported")

    def _insert(self, table):
        return (
            pg_insert(table) if self.engine.dialect.name == "postgresql" else sqlite_insert(table)
        )

    def initialize(self):
        # Worker is the sole schema initializer; the API never races DDL startup.
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(742096221)")
            metadata.create_all(conn)
            conn.execute(
                self._insert(settings)
                .values(key="schema_version", value="1")
                .on_conflict_do_nothing()
            )
            if (
                conn.scalar(select(settings.c.value).where(settings.c.key == "schema_version"))
                != "1"
            ):
                raise ValueError("Unsupported database schema version")

    def sync_nodes(self, definitions, now=None, initial_lookback=3600):
        now = time.time() if now is None else now
        with self.engine.begin() as conn:
            # Removing a node from the allowlist also revokes outstanding work.
            conn.execute(update(nodes).values(approved=False))
            for node in definitions:
                existing = (
                    conn.execute(select(nodes).where(nodes.c.node_id == node.node_id))
                    .mappings()
                    .first()
                )
                if existing:
                    old = existing["definition"]
                    for field in ("vessel_id", "bucket", "prefix", "input_format", "data_type"):
                        if old[field] != getattr(node, field):
                            raise ValueError(f"Changing {field} requires a new node ID")
                    conn.execute(
                        update(nodes)
                        .where(nodes.c.node_id == node.node_id)
                        .values(definition=node.as_dict(), approved=node.approved)
                    )
                else:
                    conn.execute(
                        insert(nodes).values(
                            node_id=node.node_id,
                            vessel_id=node.vessel_id,
                            definition=node.as_dict(),
                            approved=node.approved,
                            discovery_start=now - initial_lookback,
                        )
                    )

    def node_rows(self):
        with self.engine.connect() as conn:
            return list(conn.execute(select(nodes).order_by(nodes.c.node_id)).mappings())

    def discover(self, node, obj, processor):
        fingerprint = hashlib.sha256(
            json.dumps([node.node_id, node.bucket, obj["Key"], obj["ETag"], processor]).encode()
        ).hexdigest()
        modified = obj["LastModified"].timestamp()
        with self.engine.begin() as conn:
            conn.execute(
                self._insert(objects)
                .values(
                    fingerprint=fingerprint,
                    node_id=node.node_id,
                    bucket=node.bucket,
                    key=obj["Key"],
                    etag=obj["ETag"],
                    size=obj["Size"],
                    modified=modified,
                    processor=processor,
                    status="pending",
                    attempts=0,
                    next_attempt=0,
                    is_current=False,
                )
                .on_conflict_do_nothing(index_elements=["fingerprint"])
            )
            conn.execute(
                update(nodes)
                .where(
                    and_(
                        nodes.c.node_id == node.node_id,
                        or_(nodes.c.last_seen.is_(None), nodes.c.last_seen < modified),
                    )
                )
                .values(last_seen=modified)
            )

    def claim(self, processor, lease_seconds=900, max_attempts=5, now=None):
        now = time.time() if now is None else now
        ready = and_(
            objects.c.processor == processor,
            objects.c.attempts < max_attempts,
            nodes.c.approved.is_(True),
            or_(
                and_(objects.c.status.in_(["pending", "retry"]), objects.c.next_attempt <= now),
                and_(objects.c.status == "processing", objects.c.lease_until <= now),
            ),
        )
        token = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                update(objects)
                .where(
                    and_(
                        objects.c.status == "processing",
                        objects.c.lease_until <= now,
                        objects.c.attempts >= max_attempts,
                    )
                )
                .values(
                    status="failed",
                    error="Worker stopped during final attempt",
                    token=None,
                    lease_until=None,
                )
            )
            # Newest files first so historical catch-up cannot starve current telemetry.
            stmt = (
                select(objects.c.id)
                .join(nodes)
                .where(ready)
                .order_by(objects.c.modified.desc(), objects.c.id.desc())
                .limit(1)
            )
            if self.engine.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True, of=objects)
            job_id = conn.scalar(stmt)
            if job_id is None:
                return None
            # A conditional update also fences concurrent SQLite tests/local workers.
            result = conn.execute(
                update(objects)
                .where(
                    and_(
                        objects.c.id == job_id,
                        objects.c.attempts < max_attempts,
                        or_(
                            objects.c.status.in_(["pending", "retry"]),
                            and_(objects.c.status == "processing", objects.c.lease_until <= now),
                        ),
                    )
                )
                .values(
                    status="processing",
                    token=token,
                    lease_until=now + lease_seconds,
                    attempts=objects.c.attempts + 1,
                )
            )
            if not result.rowcount:
                return None
            return dict(
                conn.execute(select(objects).where(objects.c.id == job_id)).mappings().one()
            )

    def fail(self, job, error, max_attempts=5, now=None):
        now = time.time() if now is None else now
        with self.engine.begin() as conn:
            conn.execute(
                update(objects)
                .where(
                    and_(
                        objects.c.id == job["id"],
                        objects.c.token == job["token"],
                        objects.c.status == "processing",
                    )
                )
                .values(
                    status="failed" if job["attempts"] >= max_attempts else "retry",
                    next_attempt=now + min(3600, 30 * 2 ** (job["attempts"] - 1)),
                    token=None,
                    lease_until=None,
                    error=str(error)[:2048],
                )
            )

    def finish(self, job, rows: Iterable[dict], message_count, diagnostics="", now=None):
        now = time.time() if now is None else now
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                identity = json.dumps([job["node_id"], job["bucket"], job["key"]]).encode()
                key_lock = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
                # Serialize competing revisions of one key before locking their rows.
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (key_lock,))
            result = conn.execute(
                update(objects)
                .where(
                    and_(
                        objects.c.id == job["id"],
                        objects.c.token == job["token"],
                        objects.c.status == "processing",
                        objects.c.lease_until > now,
                        objects.c.node_id.in_(
                            select(nodes.c.node_id).where(nodes.c.approved.is_(True))
                        ),
                    )
                )
                .values(status="publishing")
            )
            if not result.rowcount:
                raise LeaseLost("Job lease expired or node was revoked; output discarded")
            batch = []
            count = 0
            for row in rows:
                batch.append(dict(row, object_id=job["id"]))
                count += 1
                if len(batch) >= 500:
                    conn.execute(insert(measurements), batch)
                    batch.clear()
            if batch:
                conn.execute(insert(measurements), batch)
            same_key = and_(
                objects.c.node_id == job["node_id"],
                objects.c.bucket == job["bucket"],
                objects.c.key == job["key"],
            )
            # Never let a slow, older revision displace a newer completed revision.
            newer = conn.scalar(
                select(objects.c.id)
                .where(and_(same_key, objects.c.id > job["id"], objects.c.status == "completed"))
                .limit(1)
            )
            if newer is None:
                conn.execute(update(objects).where(same_key).values(is_current=False))
            conn.execute(
                update(objects)
                .where(objects.c.id == job["id"])
                .values(
                    status="completed",
                    message_count=message_count,
                    measurement_count=count,
                    diagnostics=diagnostics[:16384],
                    is_current=newer is None,
                    completed_at=now,
                    token=None,
                    lease_until=None,
                    error=None,
                )
            )

    def prune(self, retention_seconds, now=None):
        now = time.time() if now is None else now
        with self.engine.begin() as conn:
            # Keep compact processing receipts permanently so old objects aren't replayed.
            return conn.execute(
                delete(measurements).where(measurements.c.timestamp < now - retention_seconds)
            ).rowcount

    def status(self):
        with self.engine.connect() as conn:
            counts = conn.execute(
                select(objects.c.status, func.count()).group_by(objects.c.status)
            ).all()
            return {
                "jobs": dict(counts),
                "latest_completed_at": conn.scalar(select(func.max(objects.c.completed_at))),
            }

    def job_rows(self, limit=100):
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(objects).order_by(objects.c.id.desc()).limit(limit)
                ).mappings()
            ]

    def measurement_rows(self, node_id, since, until, limit=1000, name=None, after=None):
        stmt = (
            select(measurements)
            .join(objects)
            .where(
                and_(
                    measurements.c.node_id == node_id,
                    measurements.c.timestamp >= since,
                    measurements.c.timestamp <= until,
                    objects.c.status == "completed",
                    objects.c.is_current.is_(True),
                )
            )
        )
        if name:
            stmt = stmt.where(measurements.c.name == name)
        if after:
            timestamp, row_id = after
            stmt = stmt.where(
                or_(
                    measurements.c.timestamp > timestamp,
                    and_(measurements.c.timestamp == timestamp, measurements.c.id > row_id),
                )
            )
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    stmt.order_by(measurements.c.timestamp, measurements.c.id).limit(limit)
                ).mappings()
            ]

    def latest(self, node_id):
        partition = [measurements.c.name, measurements.c.reference, measurements.c.src]
        ranked = (
            select(
                measurements,
                func.row_number()
                .over(
                    partition_by=partition,
                    order_by=[measurements.c.timestamp.desc(), measurements.c.id.desc()],
                )
                .label("rank"),
            )
            .join(objects)
            .where(
                and_(
                    measurements.c.node_id == node_id,
                    objects.c.is_current.is_(True),
                    objects.c.status == "completed",
                )
            )
            .subquery()
        )
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(select(ranked).where(ranked.c.rank == 1)).mappings()
            ]

    def heartbeat(self, value):
        with self.engine.begin() as conn:
            conn.execute(
                self._insert(settings)
                .values(key="worker_heartbeat", value=json.dumps(value))
                .on_conflict_do_update(index_elements=["key"], set_={"value": json.dumps(value)})
            )

    def worker_state(self):
        with self.engine.connect() as conn:
            raw = conn.scalar(select(settings.c.value).where(settings.c.key == "worker_heartbeat"))
            return json.loads(raw) if raw else None
