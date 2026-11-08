#!/bin/sh
# Entrypoint of the API image.
#
# With RUN_MIGRATIONS=true it first runs `alembic upgrade head` against DATABASE_URL
# (alembic finds its settings through ALEMBIC_CONFIG, set in the Dockerfile), then
# runs the command, uvicorn by default. Without it, it only runs the command, and
# the API checks the database itself: in production it refuses to start while
# migrations are pending. Production runs them once, from a separate job, so two
# containers never migrate at the same time.
set -eu

run_migrations=$(printf '%s' "${RUN_MIGRATIONS:-false}" | tr '[:upper:]' '[:lower:]')
case "$run_migrations" in
    true | 1 | yes)
        echo "RUN_MIGRATIONS=true: running alembic upgrade head" >&2
        alembic upgrade head
        ;;
esac

exec "$@"
