#!/bin/sh
# Migrator entrypoint (runs in the dbmate image, which includes psql).
#   migrate  - apply db/migrations, then set login-role passwords from env
#   seed     - apply db/seed/*.sql in name order (idempotent CREATE OR REPLACE)
#   status   - show migration status
set -eu

cmd="${1:-migrate}"

set_passwords() {
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q \
    -v tipg_pw="$TIPG_DB_PASSWORD" \
    -v app_pw="$APP_DB_PASSWORD" \
    -v loader_pw="$LOADER_DB_PASSWORD" \
    -v worker_pw="$WORKER_DB_PASSWORD" \
    -v analyst_pw="$ANALYST_DB_PASSWORD" \
    -f /db/roles/set-passwords.sql
  echo "migrator: role passwords set"
}

case "$cmd" in
  migrate)
    dbmate --wait --wait-timeout 60s up
    set_passwords
    ;;
  seed)
    for f in /db/seed/*.sql; do
      echo "migrator: seeding $(basename "$f")"
      psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$f"
    done
    ;;
  status)
    dbmate status
    ;;
  *)
    echo "usage: entrypoint.sh {migrate|seed|status}" >&2
    exit 2
    ;;
esac
