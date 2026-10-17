#!/bin/sh
# Explicit, one-time fixture initialisation (Phase 1-I).
# Never deletes or overwrites: an initialised root is left untouched (exit 0),
# a non-empty root without a registry is refused (exit 1).
set -eu
root=/var/lib/hererisk/fixture
cli() { python -m hererisk.cli "$@"; }

if [ -e "$root" ]; then
    if ls "$root"/elevation/rel/registry/*/current.json >/dev/null 2>&1; then
        echo '{"status": "SUCCESS", "message": "already initialised; nothing changed"}'
        exit 0
    fi
    if [ -n "$(ls -A "$root")" ]; then
        echo '{"status": "FAILED", "message": "data root not empty and has no registry; nothing changed"}'
        exit 1
    fi
else
    mkdir -m 0750 "$root"
fi
cli init-fixture-root --data-root "$root"
cli pipeline --api elevation --region 13 --source fixture-dem-png-tokyo \
    --fixture /app/fixtures/elevation-fixture --data-root "$root" --publish
