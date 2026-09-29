#!/usr/bin/env bash
# Stack lifecycle helpers behind the Makefile targets. Run via make, e.g. `make reset-db`.
#   ops.sh wait                 wait until postgis, tipg, proxy are healthy (fails fast on migrator errors)
#   ops.sh refresh              make tiPG re-read its catalog of pub views/functions
#   ops.sh backup               pg_dump -Fc to data/backups/
#   ops.sh restore <file>       replace the database with a backup
#   ops.sh reset-db             delete the database volume, rebuild from migrations + recipes + seed
#   ops.sh nuke [all]           remove containers, volumes, generated files (and images with 'all')
#   ops.sh bootstrap            first run: up, build geotools, import-all, seed, refresh
#   ops.sh migration <name>     create db/migrations/<timestamp>_<name>.sql
#
# Destructive commands ask for a typed confirmation. CONFIRM=yes skips it (scripts/CI);
# BACKUP=no skips the automatic backup offered before reset-db.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo ".env missing: run 'make env' first" >&2; exit 1; }
cli_compose_file=${COMPOSE_FILE:-}   # a COMPOSE_FILE given on the command line wins over .env
set -a; source .env; set +a
[[ -n $cli_compose_file ]] && export COMPOSE_FILE=$cli_compose_file

PROJECT=spatial
COMPOSE=(docker compose)
TOOLS=(docker compose run --rm -T geotools)

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

confirm() {  # confirm <word> <message>
  [[ ${CONFIRM:-} == yes ]] && return 0
  echo "$2"
  read -r -p "Type '$1' to continue: " answer
  [[ $answer == "$1" ]] || { echo "aborted"; exit 1; }
}

service_health() { "${COMPOSE[@]}" ps --format '{{.Health}}' "$1" 2>/dev/null || true; }

wait_healthy() {
  local deadline=$((SECONDS + ${1:-240}))
  say "waiting for postgis, tipg, proxy to become healthy"
  while ((SECONDS < deadline)); do
    local m
    m=$("${COMPOSE[@]}" ps -a --format '{{.State}} {{.ExitCode}}' migrator 2>/dev/null || true)
    if [[ $m == exited* && $m != "exited 0" ]]; then
      echo "migrator failed ($m). Its log:" >&2
      "${COMPOSE[@]}" logs --no-color migrator >&2
      exit 1
    fi
    local all=1 s
    for s in postgis tipg proxy; do
      [[ $(service_health "$s") == healthy ]] || all=0
    done
    if ((all)); then
      echo "stack healthy: http://localhost:${HTTP_PORT:-8080}/"
      return 0
    fi
    sleep 3
  done
  echo "timed out. Current state:" >&2
  "${COMPOSE[@]}" ps -a >&2
  exit 1
}

refresh() {
  # A restart is the only refresh that reaches every tiPG worker process
  # (the debug /refresh endpoint only updates the worker that handles the request).
  say "refreshing tiPG catalog (restarting tipg)"
  "${COMPOSE[@]}" restart tipg
  wait_healthy 120
}

backup() {
  mkdir -p data/backups
  local file="data/backups/${POSTGRES_DB}-$(date -u +%Y%m%dT%H%M%SZ).dump"
  say "backing up database ${POSTGRES_DB} -> ${file}"
  "${COMPOSE[@]}" exec -T postgis sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$file"
  [[ -s $file ]] || { echo "backup is empty; is postgis running?" >&2; rm -f "$file"; exit 1; }
  echo "wrote $file ($(du -h "$file" | cut -f1))"
}

restore() {
  local file=${1:-}
  [[ -f $file ]] || { echo "usage: make restore b=data/backups/<file>.dump" >&2; exit 2; }
  confirm restore "This REPLACES database '${POSTGRES_DB}' with ${file}."
  say "restoring ${file}"
  "${COMPOSE[@]}" stop tipg
  "${COMPOSE[@]}" exec -T postgis sh -c \
    'dropdb -U "$POSTGRES_USER" --force --if-exists "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
  local rc=0
  "${COMPOSE[@]}" exec -T postgis sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error' < "$file" || rc=$?
  "${COMPOSE[@]}" run --rm migrator migrate   # re-applies anything newer than the backup; resets passwords
  "${COMPOSE[@]}" start tipg
  wait_healthy 120
  ((rc == 0)) || { echo "pg_restore reported errors (exit $rc); check the output above" >&2; exit 1; }
  echo "restore complete"
}

reset_db() {
  say "datasets that are NOT rebuilt by recipes (they will be lost):"
  "${TOOLS[@]}" python scripts/geoimport.py list --no-recipe 2>/dev/null | sed 's/^/  /' || echo "  (could not list; is the stack up?)"
  confirm reset "This deletes the database volume and rebuilds it from migrations, recipes and seeds."
  if [[ ${BACKUP:-} != no ]] && [[ $(service_health postgis) == healthy ]]; then
    backup
  fi
  say "removing database volume"
  "${COMPOSE[@]}" stop proxy tipg || true
  "${COMPOSE[@]}" rm -sf postgis migrator
  docker volume rm "${PROJECT}_pgdata"
  "${COMPOSE[@]}" up -d
  wait_healthy
  say "importing recipes"
  "${TOOLS[@]}" python scripts/geoimport.py all
  say "applying seed views"
  "${COMPOSE[@]}" run --rm migrator seed
  refresh
  echo "reset-db complete"
}

nuke() {
  # Images are kept by default (the geotools build is slow); all=1 removes them too.
  # (Compose's --rmi local would also remove geotools, since Compose built it.)
  local rmi=()
  [[ ${1:-} == all ]] && rmi=(--rmi all)
  confirm nuke "This removes all containers, volumes (the database!) and generated files.
Kept: data/incoming, data/backups, data/cache/downloads, .env$([[ ${#rmi[@]} == 0 ]] && echo ", all Docker images (incl. geotools)")."
  say "removing containers, volumes${rmi:+ and images}"
  "${COMPOSE[@]}" --profile tools down -v --remove-orphans "${rmi[@]}"
  rm -rf data/cog/* data/cache/verify
  echo "done. Start again with: make bootstrap   (docs/setup/01-install.md)"
}

bootstrap() {
  say "starting stack"
  "${COMPOSE[@]}" up -d
  wait_healthy
  if ! docker image inspect "spatial/geotools:${ROCKER_TAG}" > /dev/null 2>&1; then
    say "building geotools image (first time only; this takes a while)"
    "${COMPOSE[@]}" build geotools
  fi
  say "importing recipes"
  "${TOOLS[@]}" python scripts/geoimport.py all
  say "applying seed views"
  "${COMPOSE[@]}" run --rm migrator seed
  refresh
  echo "bootstrap complete. Next: make verify"
}

migration() {
  local name=${1:-}
  [[ $name =~ ^[a-z][a-z0-9_]*$ ]] || { echo "usage: make migration n=<lowercase_name>" >&2; exit 2; }
  local file="db/migrations/$(date -u +%Y%m%d%H%M%S)_${name}.sql"
  cat > "$file" <<EOF
-- migrate:up
-- New source domain example:
--   CALL app.ensure_src_schema('src_${name#src_}');


-- migrate:down

EOF
  echo "created $file (apply with: make migrate)"
}

cmd=${1:-}
shift || true
case "$cmd" in
  wait) wait_healthy "$@" ;;
  refresh) refresh ;;
  backup) backup ;;
  restore) restore "$@" ;;
  reset-db) reset_db ;;
  nuke) nuke "$@" ;;
  bootstrap) bootstrap ;;
  migration) migration "$@" ;;
  *) sed -n '2,15p' "$0"; exit 2 ;;
esac
