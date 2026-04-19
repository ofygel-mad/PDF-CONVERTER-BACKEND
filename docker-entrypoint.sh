#!/bin/sh
set -eu

case "${RUN_MIGRATIONS:-true}" in
  1|true|TRUE|yes|YES)
    python -c "from app.main import _run_migrations; _run_migrations()"
    ;;
  *)
    echo "Skipping migrations because RUN_MIGRATIONS=${RUN_MIGRATIONS:-false}"
    ;;
esac

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/data/sessions /app/data/ocr-reviews /app/data/job-uploads
  chown -R appuser:appuser /app/data
  exec gosu appuser "$@"
fi

exec "$@"
