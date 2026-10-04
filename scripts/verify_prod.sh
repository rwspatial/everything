#!/usr/bin/env bash
# Checks a production-mode stack (compose.prod.yaml) from the outside: the public site shows published maps only and
# no admin; the admin listener (127.0.0.1:8081) has everything behind the login. Run on the server, or locally after
#   COMPOSE_FILE=compose.yaml:compose.prod.yaml PUBLIC_HTTP_BIND=127.0.0.1:8090 docker compose up -d proxy
# Usage: make verify-prod [PUBLIC_URL=https://maps.example.org] [ADMIN_URL=http://localhost:8081]
set -u
PUBLIC_URL="${PUBLIC_URL:-http://localhost:8090}"
ADMIN_URL="${ADMIN_URL:-http://localhost:${ADMIN_PORT:-8081}}"
DRAFT="${DRAFT_SLUG:-maine-lands}"        # a draft project that must stay hidden
READY="${READY_SLUG:-maine-overview}"     # a published project with charts
fails=0
check() {  # check <name> <exit-code> [detail]
  if [[ $2 == 0 ]]; then echo "  ok    $1${3:+  ($3)}"; else echo "  FAIL  $1${3:+  ($3)}"; fails=$((fails + 1)); fi
}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@"; }
adm=(-u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}")

echo "-- public site: $PUBLIC_URL"
c=$(code "$PUBLIC_URL/healthz"); [[ $c == 200 ]]; check "healthz" $? "HTTP $c"
pm=$(curl -s --max-time 10 "$PUBLIC_URL/config.json" | python3 -c 'import sys, json; print(json.load(sys.stdin).get("publicMode"))' 2>/dev/null)
[[ $pm == True ]]; check "config.json switches the frontend to public mode" $? "publicMode=$pm"
for p in /admin /admin/projects /api/admin/datasets /api/admin/auth /projects/index.json "/projects/$DRAFT/project.json"; do
  c=$(code "${adm[@]}" "$PUBLIC_URL$p"); [[ $c == 404 ]]; check "$p is not served (even with the admin login)" $? "HTTP $c"
done
list=$(curl -s --max-time 10 -H 'X-Public-Site: 0' "$PUBLIC_URL/api/projects" | python3 -c '
import sys, json; ps = json.load(sys.stdin)["projects"]; print(len(ps), all(p["status"] == "ready" for p in ps))' 2>/dev/null)
[[ $list == *True ]]; check "hub lists published (ready) maps only, whatever the client sends" $? "$list"
c=$(code "$PUBLIC_URL/api/projects/$DRAFT"); [[ $c == 404 ]]; check "a draft map is 404" $? "$DRAFT: HTTP $c"
c=$(code "$PUBLIC_URL/api/projects/$DRAFT/reports"); [[ $c == 404 ]]; check "a draft's reports are 404" $? "HTTP $c"
c=$(code "$PUBLIC_URL/api/projects/$READY"); [[ $c == 200 ]]; check "a published map is served" $? "$READY: HTTP $c"
chart=$(curl -s --max-time 20 "$PUBLIC_URL/api/projects/$READY" | python3 -c 'import sys, json; print(json.load(sys.stdin)["charts"][0]["id"])' 2>/dev/null)
c=$(code "$PUBLIC_URL/api/projects/$READY/charts/$chart"); [[ $c == 200 ]]; check "its charts are computed" $? "$chart: HTTP $c"
c=$(code -X POST "$PUBLIC_URL/api/projects"); [[ $c == 405 ]]; check "no writes on the public API" $? "HTTP $c"
h=$(curl -s -D - -o /dev/null --max-time 10 "$PUBLIC_URL/")
grep -qi '^x-content-type-options: nosniff' <<<"$h" && grep -qi '^referrer-policy:' <<<"$h" && ! grep -qi '^server:' <<<"$h"
check "security headers set, Server header removed" $?
c=$(code "$PUBLIC_URL/tiles/collections/pub.maine_water__stream_gauges/tiles/WebMercatorQuad/7/38/46"); [[ $c == 200 || $c == 204 ]]; check "map tiles are public" $? "HTTP $c"
c=$(code "$PUBLIC_URL/tiles/collections"); [[ $c == 404 ]]; check "the Data API catalogue is admin only" $? "HTTP $c"
job=$(curl -s --max-time 20 "$ADMIN_URL/tiles/collections?f=json&limit=1000" | python3 -c '
import sys, json; ids = [c["id"] for c in json.load(sys.stdin)["collections"] if c["id"].startswith("pub.analysis_sandbox__job_")]; print(ids[0] if ids else "")' 2>/dev/null)
if [[ -n $job ]]; then
  c=$(code "$PUBLIC_URL/tiles/collections/$job/tiles/WebMercatorQuad/7/38/46"); [[ $c == 404 ]]
  check "analysis results are not in the public data API" $? "$job: HTTP $c"
fi

echo "-- admin listener: $ADMIN_URL (SSH tunnel on a server)"
c=$(code "$ADMIN_URL/admin"); [[ $c == 401 ]]; check "admin asks for the login" $? "HTTP $c"
c=$(code "${adm[@]}" "$ADMIN_URL/api/admin/health"); [[ $c == 200 ]]; check "admin API works with the login" $? "HTTP $c"
c=$(code -H 'X-Public-Site: 1' "$ADMIN_URL/api/projects/$DRAFT"); [[ $c == 200 ]]
check "drafts visible to admins (a client's X-Public-Site header is ignored)" $? "HTTP $c"

if [[ "${COMPOSE_FILE:-}" == *compose.prod.yaml* ]]; then
  echo "-- compose"
  [[ -z "$(docker compose port postgis 5432 2>/dev/null)" ]]; check "PostGIS publishes no port" $?
fi

echo
if [[ $fails == 0 ]]; then echo "verify-prod: ALL CHECKS PASSED"; else echo "verify-prod: $fails check(s) FAILED"; exit 1; fi
