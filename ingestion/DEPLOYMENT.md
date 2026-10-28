# Render deployment

This increment adds a background worker, Postgres processing catalog and read-only
API. It creates separate services; it does not change the Pi, Wonder dashboard,
Wonder MQTT bridge, or objects in R2. No deployment has been performed yet.

## What is ready

`ingestion/render.yaml` defines:

- `oceanpi-ingestion-worker`: paid starter background worker.
- `oceanpi-ingestion-api`: paid starter web service with `/healthz`.
- `oceanpi-ingestion-db`: basic-1gb Postgres 17 with 10 GB storage and public
  database connections disabled. Worker and API use Render's internal URL.

All resources are in Virginia. Auto-deploy is disabled. Review Render's displayed
charges before creating these resources; this file does not quote or fix pricing.
Docker packages Python and CANboat 9.1.0 at the exact revision used in local QA.
No persistent worker disk is required: temporary files are disposable, state is
in Postgres, and original recordings stay in R2. Do not deploy this as a web
service plus a background thread: worker and API have independent lifecycles.

Official references: [Blueprints](https://render.com/docs/blueprint-spec),
[workers](https://render.com/docs/background-workers),
[Postgres](https://render.com/docs/postgresql-creating-connecting).

## Launch steps

1. Put the reviewed branch on GitHub. In Render, create a **new Blueprint** from
   `planetschool/ocean-pi`, select that branch, and set the Blueprint path to
   `ingestion/render.yaml`. Do not replace an existing Wonder service.
2. Supply the worker's `R2_ENDPOINT_URL`, existing `R2_BUCKET`,
   `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` when Render prompts.
   Use an **Object Read only** token restricted to this bucket. The worker uses
   only ListObjectsV2 and GetObject. Keep credentials in Render, not this chat,
   the Pi code, a Git commit, or a public frontend variable.
3. Confirm the proposed new resources and their charges, then create them.
   The worker initializes schema version 1 and registers `tabor-boy/nmea-main`
   for `raw/tabor-boy/`. Startup fails if the pinned decoder version differs.
4. The API may show 503 until the worker finishes database initialization.
   Render generates `API_TOKEN`; retrieve it from the API service environment
   for authenticated checks. `/healthz` requires no token and checks database
   readiness. It does not claim that telemetry is current.
5. Check `/v1/status`, `/v1/nodes`, and `/v1/latest?node_id=tabor-boy%2Fnmea-main`
   with `Authorization: Bearer <API_TOKEN>`. Confirm current capture timestamps,
   measurements and archive receipts. `/v1/objects` includes processing status,
   source keys/ETags, counts and decoder diagnostics. Expect the known PGN 126208
   warning if those control messages occur.
6. Observe at least several new archives and one worker restart. Confirm jobs
   aren't duplicated and latest readings advance. Record actual cloud latency;
   the 1–2 minute target is not guaranteed by a local decode benchmark.

Do not embed API_TOKEN in the browser bundle. The future dashboard should call a
server-side authenticated proxy or use a separately designed end-user auth flow.
This increment does not alter or deploy a dashboard UI.

## Discovery and retention

The first registration starts with a one-hour upload lookback, stored in the
registry so restarts don't reset it. Startup and hourly reconciliation scan the
registered prefix. Normal 30-second polls scan today and yesterday's UTC date
partitions. A node with another layout can set `date_partitioned: false`.
Only raw `.log`, `.log.gz`, `.raw`, `.raw.gz` objects are admitted for NMEA.

Newer uploads are processed first, in bounded cycles of up to 20 jobs. This
prioritizes current telemetry while gradually catching up. A downloaded object
is read with `IfMatch` against its cataloged ETag. An overwrite creates a new
processing identity. Duplicate listings do not duplicate measurements. The
fingerprint includes node, bucket, key, ETag and processor version; the ETag is
an object revision token, not assumed to be an MD5 checksum.

Measurements default to a **rolling 24-hour window**, with hourly cleanup and
compact processing receipts retained. R2 originals are never deleted. This is a
bounded first deployment, not a permanent full-resolution history store. The
sample generated 4,426 scalar rows/minute: approximately 6.4 million rows/day
if continuous, so inspect actual database size and query time before increasing
retention or adding vessels. Longer history will need a measured storage budget
and likely downsampling/partitioning. The 10 GB starting disk is a proposal,
not a measured capacity guarantee.

Discovery admits only objects modified since registration's cutoff and within
the retention window. Backfilled old recordings may be admitted when freshly
uploaded; measurement retention still uses their capture timestamps. Increasing
retention alone does not move a node's original registration cutoff backward.
For earlier history, use offline replay or a separately reviewed backfill job.
A prolonged outage beyond the retention window intentionally leaves older
history in R2 rather than rebuilding expired measurements.

The worker currently allows archives up to 8 MiB compressed and 16 MiB expanded.
Each converter/analyzer invocation has a 300-second deadline. Temporary disk
and workload size must be checked against real archives before raising limits.
Successful decodes can still contain protocol-level warnings; these are stored
in the processing receipt and must not be treated as proof of complete decoding.

## Nodes and processors

For more nodes, supply a Render secret file containing the format in
`nodes.example.json` and set `NODE_REGISTRY_PATH` to its path. A node must have a
unique identity and a non-overlapping prefix. Prefix, vessel, format and data
type are immutable for an existing identity; create a new identity if these
change. Removing a node or setting `approved: false` disables new claims.

The current registry is an explicit operator allowlist. It does **not** yet
scan arbitrary node manifests or automatically trust a new uploader. Additional
nodes using the supported raw NMEA format can use the existing processor;
other declared data types remain registered without being decoded. Skycam,
Sense HAT, Dolphin Cam, water-data processors and automatic manifest discovery
remain future increments. Available API measurements reflect actual stored
data, not merely a node's declared type.

## Failure behavior and operations

A job moves through pending → processing → completed, or retry → failed. Claims
have unique lease tokens; expired workers cannot publish after another claim.
Postgres claims use row locks with SKIP LOCKED. Publication inserts measurements
and marks completion in a single transaction, so partial output is rolled back.
Competing object revisions are serialized; older revisions cannot replace a
newer completed revision in API results. Reprocessing a changed object keeps
old receipts for audit, with only the newest completed revision visible.

Failures retry after 30, 60, 120 and 240 seconds, up to five attempts. A crash
on the final attempt is eventually marked failed. Failed receipts require
operator investigation; there is no public retry/write API. To retry a specific
failed object after addressing the cause, an operator can run a parameterized
SQL update of its status to `retry`, attempts to 0 and next_attempt to 0, scoped
to the exact ID. Do not reset successful receipts or truncate the catalog.

SIGTERM stops new work; an in-flight decode may finish before Render's shutdown
deadline. If forcibly stopped, the lease expires and another run retries it.
API `/v1/status` reports a stale heartbeat after five minutes; long batches can
make this stale conservatively. Errors during discovery remain visible in the
heartbeat even while existing jobs continue. Database failures prevent a new
heartbeat, so stale status must be monitored operationally.

Stop the new worker to pause ingestion. Stop the new API to remove its endpoint.
Neither action affects onboard recording, R2 uploads, or Wonder's services.
Back up Postgres before future schema upgrades; schema version 1 currently
bootstraps fresh tables but is not a general migration framework.

## Tests and remaining deployment checks

Install `requirements-cloud.lock` and `.[test]` in a Python 3.13 environment.
`TEST_DATABASE_URL` must point to a **disposable test database**: the tests drop
only their `oceanpi_*` tables between cases. Never use a production database.

Local SQLite and real PostgreSQL tests cover claims, leases, retries, revocation,
transaction rollback, object revisions, S3 SDK request contracts, API auth and
pagination, and the user-supplied Tabor Boy recording. The private recording is
not uploaded to GitHub. `.github/workflows/ingestion.yml` also exercises Postgres
17, synthetic CAN decoding and Docker build/smoke tests on Linux.

The Blueprint has been checked against Render's official JSON schema. GitHub CI
has successfully built and smoke-tested the Linux image and exercised Postgres
17. Authenticated R2 reads and a real Render rollout still require cloud access.
No live deployment or cloud latency test has been performed.
