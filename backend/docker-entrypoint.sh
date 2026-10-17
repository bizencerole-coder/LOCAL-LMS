#!/bin/sh
set -eu

if [ "${1:-serve}" = "serve" ]; then
    if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
        echo "Applying database migrations..."
        alembic upgrade head
        # After the upgrade that introduced batches, move the content folders into the
        # batch folder to match the new storage keys (does nothing once done).
        if ! python -m app.cli relocate-content --apply --quiet; then
            echo "WARNING: could not move content folders into the batch folder; run: python -m app.cli relocate-content"
        fi
    fi
    exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers "${WEB_CONCURRENCY:-2}" \
        --proxy-headers \
        --forwarded-allow-ips '*' \
        --no-access-log
fi

exec "$@"
