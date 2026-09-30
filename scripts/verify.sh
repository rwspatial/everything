#!/usr/bin/env bash
# make verify: automated Phase 1 exit-gate checks.
# Host side: container health, host exposure, HTTP through the proxy.
# Every MVT layer is named "default" (TIPG_SET_MVT_LAYERNAME=FALSE); tiles and
# style.json must agree on it (docs/decisions/0002-tipg-spike.md).
# Then scripts/verify_tools.py runs inside geotools for decoding, privileges, R/Python, imports.
set -uo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo ".env missing: run 'make env' first"; exit 1; }
cli_compose_file=${COMPOSE_FILE:-}   # a COMPOSE_FILE given on the command line wins over .env
set -a; source .env; set +a
[[ -n $cli_compose_file ]] && export COMPOSE_FILE=$cli_compose_file

BASE="http://localhost:${HTTP_PORT:-8080}"
OUT=data/cache/verify
rm -rf "$OUT"
mkdir -p "$OUT"
fails=0

check() {  # check <name> <exit-code> [detail]
  if [[ $2 == 0 ]]; then echo "PASS  $1${3:+  [$3]}"; else echo "FAIL  $1${3:+  [$3]}"; fails=$((fails + 1)); fi
}
fetch() {  # fetch <file under $OUT> <path>
  mkdir -p "$(dirname "$OUT/$1")"
  curl -fsS --max-time 60 -o "$OUT/$1" "$BASE$2"
}

echo "-- containers"
for s in postgis tipg frontend proxy; do
  h=$(docker compose ps --format '{{.Health}}' "$s" 2>/dev/null)
  [[ $h == healthy ]]; check "$s is healthy" $? "${h:-not running}"
done
m=$(docker compose ps -a --format '{{.State}} {{.ExitCode}}' migrator 2>/dev/null)
[[ $m == "exited 0" ]]; check "migrator finished successfully" $? "${m:-never ran}"

echo "-- host exposure"
pg=$(docker compose port postgis 5432 2>/dev/null || true)
[[ $pg =~ :[1-9][0-9]*$ ]] || pg=""   # unpublished prints nothing or "invalid IP:0"
if [[ ${COMPOSE_FILE:-} == *compose.dev.yaml* ]]; then
  [[ $pg == 127.0.0.1:* ]]; check "dev profile: PostGIS published on loopback only" $? "${pg:-not published}"
else
  [[ -z $pg ]]; check "locked profile: PostGIS not published to the host" $? "${pg:-not published}"
fi
px=$(docker compose port proxy 80 2>/dev/null || true)
[[ $px == 127.0.0.1:* ]]; check "proxy published on loopback only" $? "${px:-not published}"

echo "-- web app (Phase 2)"
for path in / /p/world-overview /new; do
  body=$(curl -fsS --max-time 10 "$BASE$path" 2>/dev/null)
  [[ $body == *"<!doctype html>"* && $body == *"/_app/"* ]]; check "GET $path serves the app" $?
done
fetch projects-index.json "/projects/index.json"
check "GET /projects/index.json" $?
python3 - "$OUT/projects-index.json" "$BASE" <<'EOF'
import json, sys, urllib.request
slugs = json.load(open(sys.argv[1]))["projects"]
bad = []
for s in slugs:
    try:
        m = json.load(urllib.request.urlopen(f"{sys.argv[2]}/projects/{s}/project.json", timeout=10))
        if m.get("slug") != s or m.get("manifestVersion") != 1:
            bad.append(f"{s}: slug/manifestVersion")
    except Exception as e:
        bad.append(f"{s}: {e}")
print(f"{'PASS' if not bad else 'FAIL'}  project manifests load  [{len(slugs)} projects{'; ' + '; '.join(bad) if bad else ''}]")
sys.exit(1 if bad else 0)
EOF
[[ $? == 0 ]] || fails=$((fails + 1))
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/projects/world-overview/notes.sql")
[[ $code == 404 ]]; check "/projects serves JSON only" $? "HTTP $code for a .sql path"
echo "  (full browser tests: make e2e)"

echo "-- proxy and tiPG"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/healthz")
[[ $code == 200 ]]; check "GET /healthz" $? "HTTP $code"

fetch collections.json "/tiles/collections?f=json&limit=1000"
check "GET /tiles/collections" $?
python3 - "$OUT/collections.json" <<'EOF'
import json, sys
ids = sorted(c["id"] for c in json.load(open(sys.argv[1]))["collections"])
expected = {
    "pub.world_overview__countries", "pub.world_overview__places",
    "pub.hydrology_sketch__rivers", "pub.hydrology_sketch__lakes",
    "pub.hydrology_sketch__rivers_by_rank",
}
outside = [i for i in ids if not i.startswith("pub.")]
missing = sorted(expected - set(ids))
print(f"{'PASS' if not outside else 'FAIL'}  only pub.* collections are served  [{len(ids)} collections]")
print(f"{'PASS' if not missing else 'FAIL'}  placeholder collections present"
      + (f"  [missing: {', '.join(missing)} -> make import-all && make seed && make refresh]" if missing else ""))
sys.exit(1 if outside or missing else 0)
EOF
[[ $? == 0 ]] || fails=$((fails + 1))

T=/tiles/collections
fetch tiles/countries/0/0/0.pbf "$T/pub.world_overview__countries/tiles/WebMercatorQuad/0/0/0"
check "GET vector tile (view)" $?
fetch tiles/rivers2/0/0/0.pbf "$T/pub.hydrology_sketch__rivers_by_rank/tiles/WebMercatorQuad/0/0/0?max_scalerank=2"
check "GET vector tile (function, max_scalerank=2)" $?
fetch tiles/rivers10/0/0/0.pbf "$T/pub.hydrology_sketch__rivers_by_rank/tiles/WebMercatorQuad/0/0/0?max_scalerank=10"
check "GET vector tile (function, max_scalerank=10)" $?

fetch tilejson.json "$T/pub.world_overview__countries/tiles/WebMercatorQuad/tilejson.json"
check "GET tilejson" $?
tile_url=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tiles"][0])' "$OUT/tilejson.json" 2>/dev/null)
[[ $tile_url == "$BASE/tiles/collections/"* ]]; check "tilejson URLs include the /tiles prefix (TIPG_ROOT_PATH)" $? "$tile_url"

fetch style.json "$T/pub.world_overview__countries/tiles/WebMercatorQuad/style.json"
check "GET style.json" $?
sl=$(python3 -c 'import json,sys; print(",".join(sorted({l.get("source-layer","") for l in json.load(open(sys.argv[1]))["layers"]})))' "$OUT/style.json" 2>/dev/null)
[[ $sl == default ]]; check "style.json source-layer matches tile layer name (tiPG viewer renders)" $? "source-layer=$sl"

fetch items.json "$T/pub.world_overview__countries/items?bbox=-10,35,30,60&limit=1"
check "GET items with bbox" $?

cat > "$OUT/expect.json" <<'EOF'
{
  "tiles": [
    {"file": "tiles/countries/0/0/0.pbf", "layer": "default", "min": 100},
    {"file": "tiles/rivers2/0/0/0.pbf", "layer": "default", "min": 1}
  ],
  "fewer_than": [["tiles/rivers2/0/0/0.pbf", "tiles/rivers10/0/0/0.pbf"]],
  "items": {"file": "items.json", "view": "pub.world_overview__countries", "bbox": [-10, 35, 30, 60]}
}
EOF

echo "-- inside geotools"
docker compose run --rm -T geotools python scripts/verify_tools.py
[[ $? == 0 ]] || fails=$((fails + 1))

echo
if [[ $fails == 0 ]]; then
  echo "verify: ALL CHECKS PASSED"
else
  echo "verify: $fails check group(s) FAILED (see FAIL lines above; docs/setup/99-troubleshooting.md)"
  exit 1
fi
