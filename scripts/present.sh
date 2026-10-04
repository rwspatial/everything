#!/usr/bin/env bash
# Present mode, on the AWS server (make aws-present runs it over SSH; docs/setup/10-production.md):
#   on [minutes] [password]   the public site at a temporary https://<words>.trycloudflare.com link, read-only:
#                             - Cloudflare quick tunnel (outbound only: the firewall stays closed) to the public listener
#                             - admin login off, app database roles read-only, workers stopped
#                             - Data API limited to the views behind published (ready) maps
#                             - optional viewer password (user "viewer"); the server powers off after <minutes>
#   off                       back to normal (make aws-up and make aws-deploy run this first)
#   check                     on-server checks: admin login refused, database roles read-only (exit 1 if not)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
BASE="${COMPOSE_FILE:-compose.yaml:compose.prod.yaml}"
TUNNEL_IMAGE="cloudflare/cloudflared:2026.9.3"
ROLES=(app_rw admin_api worker_rw)
sql() { docker compose exec -T postgis psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -qAtc "$1"; }

case "${1:-}" in
  on)
    minutes="${2:-90}"; password="${3:-}"
    [[ $minutes =~ ^[0-9]+$ ]] || { echo "minutes must be a number" >&2; exit 2; }
    # Only the views published maps draw (and the route badges every map shows).
    tables=$(sql "SELECT json_agg(DISTINCT c ORDER BY c) FROM (
                    SELECT l->'source'->>'collection' AS c FROM app.projects p, json_array_elements(p.manifest->'layers') l
                    WHERE p.status = 'ready'
                    UNION SELECT 'pub.maine_transportation__route_shields') x WHERE c LIKE 'pub.%'")
    docker compose stop worker dataset-worker reporter >/dev/null 2>&1 || true
    for r in "${ROLES[@]}"; do sql "ALTER ROLE $r SET default_transaction_read_only = on"; done
    PRESENT_TIPG_TABLES="$tables" COMPOSE_FILE="$BASE:compose.present.yaml" \
      docker compose up -d --no-deps core-api tipg 2>&1 | grep -iE "error" || true
    mkdir -p services/proxy/present
    rm -f services/proxy/present/*.caddy
    if [[ -n $password ]]; then
      hash=$(docker compose exec -T proxy caddy hash-password --plaintext "$password")
      printf '@present_viewers not path /healthz\nbasic_auth @present_viewers {\n\tviewer %s\n}\n' "$hash" \
        > services/proxy/present/viewer.caddy
    fi
    docker compose restart proxy >/dev/null 2>&1
    bash scripts/ops.sh wait >/dev/null 2>&1 || true
    # The tunnel: outbound to Cloudflare, into the public listener on this machine's port 80 (never the admin 8081).
    docker rm -f present-tunnel >/dev/null 2>&1 || true
    docker pull -q "$TUNNEL_IMAGE" >/dev/null
    docker run -d --name present-tunnel --network host --restart no "$TUNNEL_IMAGE" \
      tunnel --no-autoupdate --url http://127.0.0.1:80 >/dev/null
    url=""
    for _ in $(seq 1 30); do
      url=$(docker logs present-tunnel 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1 || true)
      [[ -n $url ]] && break
      sleep 2
    done
    [[ -n $url ]] || { echo "the tunnel did not start:" >&2; docker logs --tail 20 present-tunnel >&2; exit 1; }
    sudo shutdown -c >/dev/null 2>&1 || true
    sudo shutdown -h "+$minutes" >/dev/null 2>&1
    echo "URL=$url"
    ;;
  off)
    docker rm -f present-tunnel >/dev/null 2>&1 || true
    sudo shutdown -c >/dev/null 2>&1 || true
    had_password=0; compgen -G "services/proxy/present/*.caddy" >/dev/null && had_password=1
    rm -f services/proxy/present/*.caddy
    for r in "${ROLES[@]}"; do sql "ALTER ROLE $r RESET default_transaction_read_only"; done
    docker compose up -d 2>&1 | grep -iE "error" || true   # recreates core-api and tipg without the overlay
    [[ $had_password == 1 ]] && docker compose restart proxy >/dev/null
    echo "present mode off"
    ;;
  check)
    fail=0
    code=$(curl -s -o /dev/null -w '%{http_code}' -u "${ADMIN_USER:-admin}:$ADMIN_PASSWORD" http://127.0.0.1:8081/api/admin/auth)
    if [[ $code == 401 ]]; then echo "PASS admin login refused (even with the password)"; else echo "FAIL admin login: HTTP $code"; fail=1; fi
    for r in "${ROLES[@]}"; do
      v=$(sql "SELECT count(*) FROM pg_db_role_setting s JOIN pg_roles r ON r.oid = s.setrole
               WHERE r.rolname = '$r' AND 'default_transaction_read_only=on' = ANY (s.setconfig)")
      if [[ $v == 1 ]]; then echo "PASS database role $r is read-only"; else echo "FAIL database role $r is writable"; fail=1; fi
    done
    exit $fail
    ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
