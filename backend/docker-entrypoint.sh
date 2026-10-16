#!/bin/sh
set -eu

if [ "${1:-serve}" = "serve" ]; then
    if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
        echo "Applying database migrations..."
        alembic upgrade head
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
