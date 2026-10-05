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

echo "-- raster tiles (titiler, named COGs only)"
h=$(docker compose ps --format '{{.Health}}' titiler 2>/dev/null)
[[ $h == healthy ]]; check "titiler is healthy" $? "${h:-not running}"
docker compose run --rm -T geotools python scripts/verify_tools.py make-test-cog > /dev/null 2>&1
R="$BASE/raster/_verify/gradient"
ct=$(curl -s -o "$OUT/raster.png" -w '%{http_code} %{content_type}' "$R/7/38/45.png?rescale=0,1600&colormap_name=terrain")
[[ $ct == "200 image/png" && -s $OUT/raster.png ]]; check "raster tile from a COG" $? "$ct"
val=$(curl -s "$R/point/-69.2,45.2" | python3 -c 'import sys, json; print(round(json.load(sys.stdin)["values"][0]))' 2>/dev/null)
[[ $val -gt 700 && $val -lt 840 ]]; check "raster point query returns the pixel value" $? "value $val (expected ~769)"
val2=$(curl -s "$R/point/-69.2,45.2?url=https://example.com/other.tif" | python3 -c 'import sys, json; print(round(json.load(sys.stdin)["values"][0]))' 2>/dev/null)
[[ $val2 == "$val" ]]; check "client-supplied url= is ignored (no SSRF)" $? "value $val2"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/raster/_verify/gradient.tif/7/38/45.png")
[[ $code == 404 ]]; check "raster names with dots are rejected" $? "HTTP $code"
if [[ -f data/cog/maine/phzm_2023_min_temp.tif ]]; then
  M="$BASE/raster/maine/phzm_2023_min_temp"
  ct=$(curl -s -o "$OUT/maine.png" -w '%{http_code} %{content_type}' "$M/8/77/92.png?rescale=-35,5&colormap_name=rdylbu_r")
  [[ $ct == "200 image/png" && -s $OUT/maine.png ]]; check "Maine COG (hardiness grid) tile" $? "$ct"
  val=$(curl -s "$M/point/-69.78,44.31" | python3 -c 'import sys, json; print(round(json.load(sys.stdin)["values"][0]))' 2>/dev/null)
  [[ $val -gt -20 && $val -lt -5 ]]; check "Maine COG point value at Augusta" $? "${val:-none} °F (expected about -11)"
else
  echo "  --    Maine COG not built (make import-recipe r=phzm_2023_grid_me); skipped"
fi

echo "-- admin dashboard (dataset registry)"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/admin")
[[ $code == 401 ]]; check "/admin rejects anonymous visitors" $? "HTTP $code"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/admin/datasets")
[[ $code == 401 ]]; check "/api/admin rejects anonymous requests" $? "HTTP $code"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -u "${ADMIN_USER:-admin}:wrong-password" "$BASE/api/admin/datasets")
[[ $code == 401 ]]; check "/api/admin rejects a wrong password" $? "HTTP $code"
before=$(curl -s --max-time 10 -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}" "$BASE/api/admin/runs?limit=1" \
  | python3 -c 'import sys, json; r = json.load(sys.stdin); print(r[0]["id"] if r else 0)' 2>/dev/null || echo 0)
docker compose run --rm -T geotools python scripts/geoimport.py recipe me_boat_launches > "$OUT/cli-run.log" 2>&1
check "CLI recipe run (make import-recipe r=me_boat_launches) succeeds" $? "log: $OUT/cli-run.log"
python3 - "$BASE" "$before" <<'EOF'
import base64, json, os, sys, urllib.request
from pathlib import Path
base, before = sys.argv[1], int(sys.argv[2])
auth = base64.b64encode(f"{os.environ.get('ADMIN_USER', 'admin')}:{os.environ.get('ADMIN_PASSWORD', '')}".encode()).decode()
def get(path):
    req = urllib.request.Request(base + path, headers={"Authorization": f"Basic {auth}"})
    return json.load(urllib.request.urlopen(req, timeout=20))
fails = 0
def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
data = get("/api/admin/datasets")
names = {d["name"] for d in data["datasets"] if not d["orphaned"]}
yaml_names = {p.stem for p in Path("data/recipes").glob("*.yaml")}
check("registry mirrors every recipe YAML", names == yaml_names, f"{len(names)} recipes")
# "stale" means upstream has a newer version: worth refreshing, not a fault of this system. A recipe that has never run
# because a key it needs is not configured yet is waiting on the operator, so it is reported but does not fail.
def waiting_for_key(d):
    if d["status"] != "unknown" or not d.get("requires_keys"):
        return False
    configured = {k["key_name"] for k in get(f"/api/admin/datasets/{d['name']}")["keys"] if k["configured"]}
    return not set(d["requires_keys"]) <= configured
waiting = [d["name"] for d in data["datasets"] if d["enabled"] and waiting_for_key(d)]
bad = [f"{d['name']}={d['status']}" for d in data["datasets"]
       if d["enabled"] and d["name"] not in waiting
       and (d["status"] not in ("ok", "stale") or d["health_ok"] != d["outputs_total"])]
if waiting:
    print(f"  --    waiting for a key (set it in .env, then import): {', '.join(waiting)}")
stale = [d["name"] for d in data["datasets"] if d["enabled"] and d["status"] == "stale"]
check("every enabled dataset is ok with all outputs healthy", not bad, ", ".join(bad) or f"{sum(d['enabled'] for d in data['datasets'])} enabled")
if stale:
    print(f"  --    newer upstream data for: {', '.join(stale)} (Re-download and import on its dataset page)")
disabled = [d["name"] for d in data["datasets"] if not d["enabled"]]
check("disabled recipes are shown as disabled", all(d["status"] == "disabled" for d in data["datasets"] if not d["enabled"]), ", ".join(disabled) or "none")
runs = get("/api/admin/datasets/me_boat_launches")["runs"]
latest = runs[0] if runs else {}
check("the CLI run is recorded and visible in the admin API",
      latest.get("id", 0) > before and latest.get("status") == "succeeded" and latest.get("triggered_by", "").startswith("cli:"),
      f"run #{latest.get('id')} {latest.get('status')} by {latest.get('triggered_by')}")
sys.exit(1 if fails else 0)
EOF
[[ $? == 0 ]] || fails=$((fails + 1))

echo "-- projects (contracts, mapgen, registry; Maine Overview)"
docker compose run --rm -T node node scripts/contracts.mjs check 2>/dev/null | grep -E "PASS|FAIL"
check "generated frontend types match the schema" ${PIPESTATUS[0]}
docker compose run --rm -T node node scripts/validate-styles.mjs 2>&1 >/dev/null | grep -E "PASS|FAIL" | sed 's/^/      /'
check "every project's styles pass the MapLibre style spec" ${PIPESTATUS[0]}
docker compose run --rm -T geotools python scripts/mapgen.py check-templates 2>/dev/null | sed 's/^/      /'
check "every project template renders a valid manifest" ${PIPESTATUS[0]}
docker compose run --rm -T geotools python scripts/mapgen.py sync --check 2>/dev/null | tail -1 | sed 's/^/      /'
check "projects/ and the registry agree" ${PIPESTATUS[0]}
# Every project file is registered and valid (projects saved only in the /admin/new wizard may exist besides).
api=$(curl -s --max-time 10 "$BASE/api/projects" | python3 -c 'import sys, json
p = {x["slug"]: x for x in json.load(sys.stdin)["projects"]}
files = json.load(open("projects/index.json"))["projects"]
missing = [s for s in files if s not in p]; invalid = [s for s in files if s in p and not p[s]["valid"]]
print(f"{len(files)} files, {len(p)} registered" + (f"; missing {missing}" if missing else "") + (f"; invalid {invalid}" if invalid else ""))
sys.exit(1 if missing or invalid else 0)' 2>&1)
check "GET /api/projects lists every project file, all valid" $? "$api"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST --max-time 10 "$BASE/api/projects")
[[ $code == 405 ]]; check "anonymous project writes are refused" $? "HTTP $code"
census=$(docker compose exec -T postgis sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF" " -c "SELECT count(*), count(DISTINCT geoid), count(median_hh_income), round(100.0 * count(median_hh_income) / count(*), 1) FROM pub.maine_overview__towns"' 2>/dev/null)
read -r n uniq inc pct <<<"$census"
[[ $n == 529 && $uniq == 529 ]]; check "Maine towns: 529 county subdivisions, unique GEOIDs" $? "${n:-?} rows, ${uniq:-?} unique"
python3 -c "import sys; sys.exit(0 if float('${pct:-0}') >= 93 else 1)"
check "Maine towns: ACS income joined (the rest are Census-suppressed small places)" $? "${inc:-?} of ${n:-?} (${pct:-?} %)"
size=$(curl -s -o "$OUT/towns.pbf" -w '%{http_code} %{size_download}' "$BASE/tiles/collections/pub.maine_overview__towns/tiles/WebMercatorQuad/7/38/46")
[[ ${size% *} == 200 && ${size#* } -gt 1000 ]]; check "Maine towns: z7 tile over Augusta has features" $? "$size bytes"
# Round trip: a manifest saved through the API (the wizard's path) and exported by the CLI is byte-identical.
python3 -c 'import json; m = json.load(open("projects/maine-overview/project.json")); m["slug"] = "zz-verify-roundtrip"; m["title"] = "Round trip – Maine"; print(json.dumps(m, indent=2, ensure_ascii=False))' > "$OUT/rt.json"
curl -s -o /dev/null -X DELETE -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}" "$BASE/api/admin/projects/zz-verify-roundtrip"
code=$(curl -s -o "$OUT/rt.resp" -w '%{http_code}' -X POST -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}" --data-binary @"$OUT/rt.json" "$BASE/api/admin/projects")
docker compose run --rm -T geotools python scripts/mapgen.py export zz-verify-roundtrip --stdout > "$OUT/rt.out" 2>/dev/null
[[ $code == 201 ]] && cmp -s "$OUT/rt.json" "$OUT/rt.out"; check "wizard save -> mapgen export round trip is byte-identical" $? "create HTTP $code"
curl -s -o /dev/null -X DELETE -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}" "$BASE/api/admin/projects/zz-verify-roundtrip"
# Invalid manifests fail with specific codes.
python3 -c 'import json; m = json.load(open("projects/maine-overview/project.json")); m["slug"] = "zz-verify-invalid"; m["layers"][0]["source"]["collection"] = "pub.maine_overview__nope"; print(json.dumps(m))' > "$OUT/bad.json"
codes=$(curl -s -X POST -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}" --data-binary @"$OUT/bad.json" "$BASE/api/admin/projects" | python3 -c 'import sys, json; print(",".join(e["code"] for e in json.load(sys.stdin)["detail"]["errors"]))' 2>/dev/null)
[[ $codes == E_VIEW_MISSING ]]; check "a manifest pointing at a missing view is refused with E_VIEW_MISSING" $? "${codes:-no answer}"
# A published view may only read src_* and pub (otherwise it could expose e.g. the app registry through tiPG).
psql_owner() { docker compose exec -T postgis sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq'; }
echo "CREATE OR REPLACE VIEW pub.zz_verify__leak AS SELECT row_number() OVER ()::int AS id, ST_SetSRID(ST_MakePoint(-69, 45), 4326)::geometry(Point, 4326) AS geom, name FROM app.recipes;" | psql_owner
python3 -c 'import json; m = json.load(open("projects/maine-overview/project.json")); m["slug"] = "zz-verify-leak"; l = m["layers"][0]; l["source"] = {"type": "tipg-vector", "collection": "pub.zz_verify__leak"}; l["interaction"] = {"inspect": True}; l["style"]["layers"] = l["style"]["layers"][1:]; print(json.dumps(m))' > "$OUT/leak.json"
codes=$(curl -s -X POST -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}" --data-binary @"$OUT/leak.json" "$BASE/api/admin/projects/validate" | python3 -c 'import sys, json; print(",".join(e["code"] for e in json.load(sys.stdin)["errors"]))' 2>/dev/null)
echo "DROP VIEW IF EXISTS pub.zz_verify__leak;" | psql_owner
[[ $codes == E_VIEW_SOURCE ]]; check "a view reading the app registry is refused with E_VIEW_SOURCE" $? "${codes:-no answer}"
# Tile filters must reach a spatial index: a view that wraps its geometry (ST_Force2D, casts) scans the whole table.
idx=$(curl -s --max-time 60 -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}" "$BASE/api/admin/database?refresh=true" | python3 -c 'import sys, json
d = json.load(sys.stdin); s = d["summary"]; bad = [v["name"] for v in d["views"] if v["spatial_index_usable"] is not True]
print("%d of %d" % (s["views_indexed"], s["views"]) + ("; not: %s" % bad[:6] if bad else ""))
sys.exit(1 if bad else 0)' 2>&1)
check "every published view can use a spatial index for its tile filter (/admin/database)" $? "$idx"
units=$(echo "SELECT count(*) FROM app.units u WHERE to_regclass(u.collection) IS NOT NULL AND u.unit_count > 0;" | psql_owner)
[[ $units == 7 ]]; check "project builder: 7 units cataloged, each with its pub.units__* view" $? "${units:-?} of 7"

echo "-- dataset worker (admin Phase B)"
docker compose --profile workers --profile mcp --profile tools --profile test config 2>/dev/null | grep -q "docker.sock"
[[ $? != 0 ]]; check "no service mounts the Docker socket" $?
h=$(docker compose --profile workers ps --format '{{.Health}}' dataset-worker 2>/dev/null)
if [[ $h == healthy ]]; then
  check "dataset worker is healthy" 0
  adm=(-s -u "${ADMIN_USER:-admin}:${ADMIN_PASSWORD:-}")
  act() { curl "${adm[@]}" -X POST "$BASE/api/admin/datasets/$1/actions" -H 'Content-Type: application/json' -d "{\"action\":\"$2\"}"; }
  jid() { python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])'; }
  waitjob() { for _ in $(seq 1 90); do s=$(curl "${adm[@]}" "$BASE/api/admin/jobs/$1" | python3 -c 'import sys, json; print(json.load(sys.stdin)["status"])'); case $s in succeeded|failed|cancelled) break;; esac; sleep 2; done; echo "$s"; }
  j=$(act me_cousub dry_run | jid); s=$(waitjob "$j")
  plan=$(curl "${adm[@]}" "$BASE/api/admin/jobs/$j" | python3 -c 'import sys, json; p = json.load(sys.stdin)["result"]["plan"]; print(p["upstream_bytes"], p["cached_bytes"], p["current_rows"])')
  read -r up cached rows <<<"$plan"
  [[ $s == succeeded && -n $up && $up == "$cached" && $rows == 529 ]]; check "dry run (Maine towns): upstream size = cached download, 529 rows" $? "$s; upstream $up, cached $cached"
  j=$(act me_cousub redownload | jid)
  dup=$(act me_cousub import | python3 -c 'import sys, json; d = json.load(sys.stdin); print(d["id"], d.get("deduplicated"))')
  [[ $dup == "$j True" ]]; check "a second click on a queued dataset job returns the same job" $? "$dup"
  s=$(waitjob "$j")
  n=$(docker compose exec -T postgis sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM pub.maine_overview__towns"')
  [[ $s == succeeded && $n == 529 ]]; check "re-download via the dashboard API; the published view survives" $? "$s; pub.maine_overview__towns $n rows"
  printf 'name: zz_verify_unreachable\ntitle: verify (unreachable source)\nsource:\n  url: http://127.0.0.1:9/nothing.zip\ntarget: src_census.zz_verify_unreachable\nenabled: true\n' > data/recipes/zz_verify_unreachable.yaml
  docker compose run --rm -T geotools python scripts/geoimport.py sync > /dev/null 2>&1
  j=$(act zz_verify_unreachable redownload | jid)
  for _ in $(seq 1 60); do r=$(curl "${adm[@]}" "$BASE/api/admin/jobs/$j" | python3 -c 'import sys, json; d = json.load(sys.stdin); print(d["status"], d["attempts"], (d.get("error") or {}).get("message", "")[:60])'); [[ $r == failed* ]] && break; sleep 3; done
  rm -f data/recipes/zz_verify_unreachable.yaml
  docker compose exec -T postgis sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -qc "DELETE FROM app.recipes WHERE name = '"'"'zz_verify_unreachable'"'"'"'
  [[ $r == "failed 4 "* ]]; check "an unreachable source is retried 4 times with backoff, then fails" $? "$r"
else
  echo "  --    dataset worker not running (make workers-up); dataset job checks skipped"
fi

echo "-- MCP servers (Phase 4)"
if grep -qE '^MCP_DB_PASSWORD=.' .env; then
  docker compose run --rm -T --no-deps mcp-db python tests/smoke_spatial_db.py 2>/dev/null | sed 's/^/      /'
  check "spatial-db MCP server: Maine answers over stdio, writes and slow queries refused" ${PIPESTATUS[0]}
  bash scripts/mcp_pipeline_e2e.sh 2>/dev/null | sed 's/^/      /'
  check "project-pipeline MCP server: explore -> propose -> validate -> apply (approved) -> published" ${PIPESTATUS[0]}
  if [[ $(docker compose --profile workers ps --format '{{.Health}}' worker 2>/dev/null) == healthy ]]; then
    docker compose run --rm -T --no-deps mcp-analysis python tests/smoke_analysis.py 2>/dev/null | sed 's/^/      /'
    check "analysis MCP server: Python and R jobs on Maine towns, cancel, scoped token" ${PIPESTATUS[0]}
  else
    echo "  --    analysis worker not running (make workers-up); analysis checks skipped"
  fi
else
  echo "  --    MCP_DB_PASSWORD not set (make mcp-credentials); MCP checks skipped"
fi

echo "-- architecture doc"
bash scripts/check_architecture.sh
[[ $? == 0 ]] || fails=$((fails + 1))

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
