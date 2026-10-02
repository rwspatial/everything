#!/bin/sh
# Migrator entrypoint (runs in the dbmate image, which includes psql).
#   migrate  - apply db/migrations, then set login-role passwords from env
#   seed     - apply db/seed/*.sql, then every projects/<slug>/sql/*.sql, in name order (idempotent)
#   project <slug> - apply one project's projects/<slug>/sql/*.sql (mapgen apply)
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
    -v admin_api_pw="$ADMIN_API_DB_PASSWORD" \
    -f /db/roles/set-passwords.sql
  echo "migrator: role passwords set"
}

case "$cmd" in
  migrate)
    dbmate --wait --wait-timeout 60s up
    set_passwords
    ;;
  seed)
    for f in /db/seed/*.sql /projects/*/sql/*.sql; do
      [ -f "$f" ] || continue
      echo "migrator: seeding ${f#/}"
      psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$f"
    done
    ;;
  project)
    slug="${2:-}"
    case "$slug" in
      ''|*[!a-z0-9-]*) echo "usage: entrypoint.sh project <slug>  (lowercase letters, digits, dashes)" >&2; exit 2 ;;
    esac
    found=0
    for f in /projects/"$slug"/sql/*.sql; do
      [ -f "$f" ] || continue
      found=1
      echo "migrator: applying ${f#/}"
      psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -1 -f "$f"
    done
    [ "$found" = 1 ] || echo "migrator: projects/$slug/sql/ has no .sql files (nothing to apply)"
    ;;
  status)
    dbmate status
    ;;
  *)
    echo "usage: entrypoint.sh {migrate|seed|project <slug>|status}" >&2
    exit 2
    ;;
esac
