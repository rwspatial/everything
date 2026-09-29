#!/bin/bash
# Writes a libpq service file from env so every tool connects by name and no
# password ever appears on a command line:
#   ogr2ogr ... PG:"service=loader"      psql service=analyst
#   R:  DBI::dbConnect(RPostgres::Postgres())          (uses PGSERVICE, default: analyst)
#   Py: psycopg.connect("service=analyst")
set -euo pipefail

mkdir -p "$HOME"
old_umask=$(umask)
umask 077
cat > "$HOME/.pg_service.conf" <<EOF
[loader]
host=${PGHOST}
port=${PGPORT}
dbname=${PGDATABASE}
user=loader
password=${LOADER_DB_PASSWORD}

[analyst]
host=${PGHOST}
port=${PGPORT}
dbname=${PGDATABASE}
user=analyst_ro
password=${ANALYST_DB_PASSWORD}

[tipg]
host=${PGHOST}
port=${PGPORT}
dbname=${PGDATABASE}
user=tipg_ro
password=${TIPG_DB_PASSWORD}
EOF
umask "$old_umask"

export PGSERVICEFILE="$HOME/.pg_service.conf"
export PGSERVICE="${PGSERVICE:-analyst}"
unset LOADER_DB_PASSWORD ANALYST_DB_PASSWORD TIPG_DB_PASSWORD

exec "$@"
