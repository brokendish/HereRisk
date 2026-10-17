# HereRisk elevation API - fixture deployment image (Phase 1-I).
# Build context: the repository root (see compose.yaml). Only the files
# allowed by Dockerfile.dockerignore enter the image: no secrets, no real data.
FROM python:3.14.3-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY deploy/fixture-vps/requirements.txt /tmp/requirements.txt
RUN pip install --only-binary=:all: --no-deps -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && groupadd --system --gid 10001 hererisk \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
      --shell /usr/sbin/nologin hererisk \
 && install -d -o 10001 -g 10001 -m 0750 /var/lib/hererisk

WORKDIR /app
COPY src/hererisk /app/src/hererisk
COPY api/elevation/conf /app/api/elevation/conf
COPY tests/fixtures/elevation-fixture /app/fixtures/elevation-fixture
COPY deploy/fixture-vps/init-fixture.sh /app/bin/init-fixture.sh

USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "hererisk.elevation.api.server", "--help"]
