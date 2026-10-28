# Ocean Pi ingestion foundation

A Render-ready worker and read-only API built around the existing R2 archive.
Tabor Boy's Raspberry Pi and Wonder's dashboard/bridge remain unchanged. The
package never publishes MQTT or writes/deletes R2 objects.

The real Tabor Boy recording passed local replay before this registry and
processing tracker were added. This increment adds:

- An approved node registry preserving `raw/tabor-boy/YYYY/MM/DD/HHMMSS.log.gz`.
- Paginated R2 discovery and conditional reads of cataloged object revisions.
- CANboat 9.1.0 decoding, fast-packet reassembly and selected measurement export.
- Postgres job tracking, retries, crash recovery and transactional publication.
- Authenticated node, status, latest-measurement and paginated history APIs.
- A Docker image definition, Render Blueprint and PostgreSQL/Linux CI workflow.

**Start with [DEPLOYMENT.md](DEPLOYMENT.md)** for the exact launch steps, settings,
retention policy and remaining cloud verification. Nothing has been deployed yet.

## Existing repositories inspected

- `planetschool/ocean-pi`: production sensor scripts. Wonder uses CANboat and
  writes `{received_utc, source, message}` JSONL. These scripts are untouched.
- `planetschool/ocean-pi-mqtt-bridge`: Wonder MQTT-to-HTTP service, unchanged.
- `planetschool/ocean-pi-wonder-dashboard`: existing dashboard, unchanged.
- `planetschool/ocean-pi-docs`: educational documentation.
- `planetschool/oceanpi-atlas`: Atlas Scientific I2C library, unrelated to ingestion.

## Local use

Offline replay uses Python 3.10+ with no Python runtime dependencies. Cloud
services use Python 3.13 with dependencies pinned in `requirements-cloud.lock`.
Install CANboat separately for local raw replay, or use the Docker definition
that builds its pinned source revision. See the official
[analyzer](https://github.com/canboat/canboat/wiki/analyzer) and
[candump converter](https://github.com/canboat/canboat/wiki/candump2analyzer) guides.

```sh
python3 -m oceanpi_ingest /path/to/HHMMSS.log.gz \
  --node-id tabor-boy/nmea-main --format candump \
  --output tabor-boy-decoded.jsonl
```

Use `--analyzer` and `--converter` when the tools aren't on PATH. Select
`--format canboat` for CANboat native text. `--format jsonl` accepts already
decoded CANboat JSON or Wonder's existing envelope. Choose formats after
inspecting the file; the suffix alone is insufficient. Gzip is detected by
content. Existing output files are never overwritten, and a failed run does
not publish partial output.

For direct R2 CLI replay, install `pip install -e '.[r2]'` into a virtual
environment and configure a local AWS profile with a bucket-scoped Object Read
only token. Supply the R2 S3 endpoint, not a public R2 camera URL.

```sh
python3 -m oceanpi_ingest r2://BUCKET/raw/tabor-boy/YYYY/MM/DD/HHMMSS.log.gz \
  --profile oceanpi-readonly --endpoint https://ACCOUNT.r2.cloudflarestorage.com \
  --node-id tabor-boy/nmea-main --format candump --output decoded.jsonl
```

The offline CLI writes a versioned envelope retaining original decoded messages.
`oceanpi_ingest.measurements.extract` selects GPS, heading, depth, apparent/true
wind, attitude and COG/SOG fields with explicit units and reference qualifiers.
It expects CANboat's default metric/degree output, not arbitrary JSON produced
with `-si` or custom unit settings. Measurement timestamps are normalized UTC
capture timestamps, not inferred sensor sampling times. Missing values are
omitted, never converted to zero.

The cloud worker stores selected measurements and processing receipts in
Postgres, with raw source recordings retained in R2. It does not retain a
second copy of every decoded proprietary message in Postgres. Current history
retention defaults to 24 hours; full-resolution permanent history is a later
storage design decision.

## Validation

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-cloud.lock -e '.[test]'
CANBOAT_ANALYZER=/path/to/analyzer \
CANBOAT_CONVERTER=/path/to/candump2analyzer \
TABOR_RECORDING=/path/to/raw_tabor-boy_2026_10_28_220400.log.gz \
.venv/bin/python -m unittest discover -s tests -v
```

Cloud tests default to a temporary SQLite database. Set `TEST_DATABASE_URL` to a
**disposable PostgreSQL database** to exercise the real Postgres implementation
and concurrent workers. Tests drop the `oceanpi_*` tables in that test database.
Never use production credentials. Tests requiring unavailable executables or
the private recording are skipped. The recording and generated artifacts are
ignored by Git.

The real one-minute recording produced 7,459 messages across 43 PGNs and 4,426
selected measurements. Independent replay was identical; the complete
worker → PostgreSQL → API path reproduced those counts without duplicate jobs.
CANboat reported 54 incomplete repeating-set errors on control PGN 126208,
retained in the processing receipt; no measurements are extracted from it.
This does not establish complete protocol coverage or calibrated instrument
accuracy. CANboat can skip malformed raw frames without failing the process.

To reproduce the offline QA artifacts:

```sh
python3 validate_recording.py /path/to/raw_tabor-boy_2026_10_28_220400.log.gz \
  --analyzer /path/to/analyzer --converter /path/to/candump2analyzer \
  --output-dir validation/new-run
```

The validator requires a new directory and loads this small recording into
memory for comparison. The worker instead uses temporary disk and batched
publication. It enforces archive size limits and subprocess deadlines; its
progress survives restarts in Postgres.

Authenticated R2 access, Linux image execution and a Render rollout are separate
checks described in the deployment guide. New data processors, automatic node
manifest discovery and the new dashboard UI are not included in this increment.
