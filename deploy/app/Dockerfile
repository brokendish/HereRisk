# HereRisk application image (Phase 3-G): one image for location-api, elevation-api and
# data-inventory (see compose.yaml at the repository root).
# Build context: the repository root. Only the files allowed by Dockerfile.dockerignore enter the
# image: application code, its settings, the public source ledger and the elevation fixture.
# No official data, token or local settings file (they are mounted read only at run time).
# Same base as Phase 1-I; shapely / numpy are pinned binary wheels (no compiler in the image).
FROM python:3.14.3-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY deploy/app/requirements.txt /tmp/requirements.txt
RUN pip install --only-binary=:all: --no-deps -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && groupadd --system --gid 10001 hererisk \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
      --shell /usr/sbin/nologin hererisk \
 && install -d -o 10001 -g 10001 -m 0750 /var/lib/hererisk /var/lib/hererisk-flood /var/lib/hererisk-flood-diag \
      /var/lib/hererisk-tsunami

WORKDIR /app
# root-owned and world-readable, never writable by the service user
COPY --chmod=a+rX,go-w src/hererisk /app/src/hererisk
COPY --chmod=a+rX,go-w api/elevation/conf /app/api/elevation/conf
COPY --chmod=a+rX,go-w docs/data-sources/official-source-ledger.json /app/docs/data-sources/official-source-ledger.json
COPY --chmod=a+rX,go-w tests/fixtures/elevation-fixture /app/fixtures/elevation-fixture
COPY --chmod=a+rX,go-w deploy/fixture-vps/init-fixture.sh /app/bin/init-fixture.sh

USER 10001:10001
CMD ["python", "-m", "hererisk.location.server", "--help"]
