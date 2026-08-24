#!/usr/bin/env sh
# Apply migrations, then start the API.
#
# Kept separate from the Dockerfile CMD so a deployment can run migrations as a
# one-off job instead — running them from every replica races when more than one
# starts at once. Alembic takes an advisory lock, so the race is safe, but it is
# still the wrong shape for a multi-replica rollout.
set -eu

echo "Applying database migrations..."
alembic upgrade head

echo "Starting API..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips '*' \
    --timeout-graceful-shutdown 45
