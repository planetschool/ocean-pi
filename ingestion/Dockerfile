FROM python:3.13-slim-bookworm AS canboat
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src/canboat
# Immutable revision validated against the real Tabor Boy recording.
ARG CANBOAT_REF=5b8340403e009b935f6a398b1ef0244a03e3d128
RUN git init . && git remote add origin https://github.com/canboat/canboat.git \
    && git fetch --depth 1 origin "$CANBOAT_REF" && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$CANBOAT_REF" \
    && make -C analyzer analyzer BUILDDIR=rel/build \
    && make -C candump2analyzer BUILDDIR=rel/build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=canboat /src/canboat/rel/build/analyzer /usr/local/bin/analyzer
COPY --from=canboat /src/canboat/rel/build/candump2analyzer /usr/local/bin/candump2analyzer
COPY --from=canboat /src/canboat/LICENSE /usr/share/licenses/canboat/LICENSE
COPY requirements-cloud.lock ./
RUN pip install --no-cache-dir -r requirements-cloud.lock
COPY pyproject.toml README.md ./
COPY oceanpi_ingest ./oceanpi_ingest
RUN pip install --no-cache-dir --no-deps . \
    && useradd --system --uid 10001 oceanpi \
    && analyzer -version
USER oceanpi
CMD ["python", "-m", "oceanpi_ingest.worker"]
