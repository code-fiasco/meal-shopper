#!/bin/sh
# Start as root so a newly created /data mount can be made writable, then drop privileges.
set -eu

mkdir -p /data
chown app:app /data

gosu app alembic upgrade head
exec gosu app uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT:-8000}"
