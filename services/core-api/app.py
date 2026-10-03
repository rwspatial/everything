"""core-api: admin backend for the dataset dashboard (plan: .claude/plans/admin-dashboard.plan.md).

Phase A is read-only. It connects as `admin_api`, which can only SELECT the registry tables in `app`.
It never holds external API keys and never touches files.

Auth: HTTP Basic, checked here for every /api/admin/* request, and for the /admin pages via Caddy
`forward_auth` -> GET /api/admin/auth. Replace with OIDC when this leaves localhost (plan §8).
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "contracts"))
import validate as V  # noqa: E402  contracts/validate.py, shared with mapgen

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
REALM = 'Basic realm="Spatial admin", charset="UTF-8"'

pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5, open=False,
                      kwargs={"row_factory": dict_row, "autocommit": True})
# Projects (Phase 3) use app_rw: read pub views, write app.projects / app.manifest_versions only.
projects_pool = ConnectionPool(os.environ["PROJECTS_DATABASE_URL"], min_size=1, max_size=5, open=False,
                               kwargs={"row_factory": dict_row, "autocommit": True,
                                       "options": "-c statement_timeout=10000"})  # field stats scan views
TITILER = os.environ.get("TITILER_URL", "http://titiler:8000")
# Where titiler reads the COGs: data/cog mounted at /data/cog, or s3://<bucket>/<prefix> (compose.s3.yaml).
COG_ROOT = os.environ.get("COG_ROOT", "/data/cog").rstrip("/")
MAX_MANIFEST_BYTES = 1_000_000


@asynccontextmanager
async def lifespan(_app: FastAPI):
    pool.open(wait=True, timeout=30)
    projects_pool.open(wait=True, timeout=30)
    yield
    projects_pool.close()
    pool.close()


app = FastAPI(title="Spatial admin API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# ---- auth ------------------------------------------------------------------------------------

def _credentials_ok(request: Request) -> bool:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        return False
    try:
        user, _, password = base64.b64decode(header[6:].strip()).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    # Constant-time comparisons for both parts.
    return hmac.compare_digest(user.encode(), ADMIN_USER.encode()) & hmac.compare_digest(
        password.encode(), ADMIN_PASSWORD.encode())


def require_admin(request: Request) -> None:
    if not _credentials_ok(request):
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": REALM})


# The project-pipeline MCP server has its own credential: a bearer token that only opens project validation and
# field statistics (read-only), never saving, datasets or runs. Empty = disabled. It reaches core-api on the
# internal api network; through the proxy, /api/admin/* also needs the admin login (Caddy forward_auth).
PIPELINE_TOKEN = os.environ.get("MCP_PIPELINE_TOKEN", "")


def _bearer_is(request: Request, token: str) -> bool:
    header = request.headers.get("authorization", "")
    return bool(token) and header.lower().startswith("bearer ") and hmac.compare_digest(
        header[7:].strip().encode(), token.encode())


def require_admin_or_pipeline(request: Request) -> None:
    if not _bearer_is(request, PIPELINE_TOKEN):
        require_admin(request)


# The analysis MCP server's token: list processes, submit jobs, read and cancel them. Not promotion, not projects.
ANALYSIS_TOKEN = os.environ.get("MCP_ANALYSIS_TOKEN", "")


def require_admin_or_analysis(request: Request) -> None:
    if not _bearer_is(request, ANALYSIS_TOKEN):
        require_admin(request)


def _caller(request: Request) -> str:
    return "mcp:analysis" if _bearer_is(request, ANALYSIS_TOKEN) else _admin_user(request)


@app.get("/internal/healthz", include_in_schema=False)
def healthz() -> dict:
    """Container healthcheck (not routed by the proxy)."""
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/api/admin/auth")
def auth(request: Request) -> Response:
    """Target of Caddy forward_auth for /admin pages: 204 when logged in, else a Basic challenge."""
    if _credentials_ok(request):
        return Response(status_code=204)
    return Response(status_code=401, headers={"WWW-Authenticate": REALM}, content="authentication required")


# ---- helpers ---------------------------------------------------------------------------------

def rows(sql: str, params: Any = None) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def one(sql: str, params: Any = None) -> dict | None:
    r = rows(sql, params)
    return r[0] if r else None


BBOX = "CASE WHEN {b} IS NULL THEN NULL ELSE json_build_array(ST_XMin({b}), ST_YMin({b}), ST_XMax({b}), ST_YMax({b})) END"


def dataset_status(d: dict) -> str:
    """One word for the table: failed > unhealthy > stale > disabled > ok > unknown."""
    if d.get("last_run") and d["last_run"]["status"] == "failed":
        return "failed"
    if d.get("health_fail"):
        return "unhealthy"
    if d.get("freshness") == "stale":
        return "stale"
    if not d.get("enabled"):
        return "disabled"
    if d.get("outputs_total") and not d.get("health_warn"):
        return "ok"
    return "unknown"


DATASETS_SQL = f"""
SELECT r.name, r.title, r.description, r.agency, r.kind, r.group_name, r.enabled, r.license, r.attribution,
       r.vintage, r.coverage, r.requires_keys, r.yaml_path IS NULL AS orphaned, r.sync_error, r.synced_at,
       c.extent_name, c.received_ratio::float8 AS received_ratio, {BBOX.format(b="c.bbox")} AS bbox,
       o.outputs_total, o.health_ok, o.health_warn, o.health_fail, o.rows, o.bytes, o.projects,
       fc.verdict AS freshness, fc.checked_at AS freshness_checked_at,
       p.parts_total, p.parts_current,
       lr.last_run
FROM app.recipes r
LEFT JOIN app.coverages c ON c.recipe_name = r.name
LEFT JOIN LATERAL (
  SELECT count(*) AS outputs_total,
         count(*) FILTER (WHERE health = 'ok') AS health_ok,
         count(*) FILTER (WHERE health = 'warn') AS health_warn,
         count(*) FILTER (WHERE health = 'fail') AS health_fail,
         (sum(row_count) FILTER (WHERE kind = 'postgis_table'))::bigint AS rows,
         (sum(bytes) FILTER (WHERE kind = 'postgis_table'))::bigint AS bytes,
         (SELECT array_agg(DISTINCT pj ORDER BY pj) FROM app.dataset_outputs x, unnest(x.projects) pj
           WHERE x.recipe_name = r.name) AS projects
  FROM app.dataset_outputs WHERE recipe_name = r.name) o ON true
LEFT JOIN LATERAL (
  SELECT verdict, checked_at FROM app.freshness_checks WHERE recipe_name = r.name ORDER BY checked_at DESC LIMIT 1) fc ON true
LEFT JOIN LATERAL (
  SELECT count(*) AS parts_total, count(*) FILTER (WHERE status = 'current') AS parts_current
  FROM app.dataset_parts WHERE recipe_name = r.name AND loaded_version IS NOT NULL) p ON true
LEFT JOIN LATERAL (
  SELECT json_build_object('id', id, 'status', status, 'action', action, 'triggered_by', triggered_by,
                           'finished_at', finished_at, 'started_at', started_at) AS last_run
  FROM app.runs WHERE recipe_name = r.name ORDER BY id DESC LIMIT 1) lr ON true
"""


# ---- API -------------------------------------------------------------------------------------

@app.get("/api/admin/health", dependencies=[Depends(require_admin)])
def api_health() -> dict:
    return {"ok": True, "db": one("SELECT now() AS now, current_user AS role")}


# ---- database health: indexes, geometry types, scan counts (/admin/database) -----------------------------------
# The check that matters most for the maps: can each pub view's tile filter (geom && tile envelope) use a spatial
# index? A view that wraps its geometry (ST_Force2D(geom), geom::geometry(Point, 4326), ST_PointOnSurface(geom))
# hides the GiST index, and then every tile scans the whole source table. geoimport.normalize_geometry gives
# source columns one concrete 2D type at import so views can pass geom through untouched.
# (These queries run without parameters, so % is literal.)

DB_VIEWS_SQL = r"""
SELECT c.relname AS name, a.attname AS geom, postgis_typmod_type(a.atttypmod) AS geometry_type,
       c.relname LIKE 'analysis\_sandbox\_\_job\_%' AS analysis_output,
       (SELECT array_agg(DISTINCT n2.nspname || '.' || t.relname)
          FROM pg_rewrite r JOIN pg_depend d ON d.objid = r.oid
          JOIN pg_class t ON t.oid = d.refobjid JOIN pg_namespace n2 ON n2.oid = t.relnamespace
         WHERE r.ev_class = c.oid AND t.oid <> c.oid AND t.relkind IN ('r', 'v', 'm', 'p')) AS sources
FROM pg_class c
JOIN LATERAL (SELECT attname, atttypmod FROM pg_attribute WHERE attrelid = c.oid AND atttypid = 'geometry'::regtype
              AND attnum > 0 AND NOT attisdropped ORDER BY attnum LIMIT 1) a ON true
WHERE c.relnamespace = 'pub'::regnamespace AND c.relkind IN ('v', 'm')
ORDER BY 1"""

DB_TABLES_SQL = r"""
SELECT n.nspname AS schema, c.relname AS name, greatest(c.reltuples, 0)::bigint AS rows,
       pg_total_relation_size(c.oid) AS bytes,
       a.attname AS geom, postgis_typmod_type(a.atttypmod) AS geometry_type, postgis_typmod_dims(a.atttypmod) AS dims,
       a.attname IS NOT NULL AND EXISTS (
         SELECT 1 FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_am am ON am.oid = ic.relam
          WHERE i.indrelid = c.oid AND am.amname IN ('gist', 'spgist', 'brin') AND a.attnum = ANY (i.indkey)) AS spatial_index,
       (SELECT count(*) FROM pg_index i WHERE i.indrelid = c.oid) AS indexes,
       s.seq_scan, s.seq_tup_read, s.idx_scan, s.n_live_tup, s.n_dead_tup,
       greatest(s.last_analyze, s.last_autoanalyze) AS last_analyzed,
       greatest(s.last_vacuum, s.last_autovacuum) AS last_vacuumed
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN LATERAL (SELECT attname, atttypmod, attnum FROM pg_attribute WHERE attrelid = c.oid
                   AND atttypid = 'geometry'::regtype AND attnum > 0 AND NOT attisdropped ORDER BY attnum LIMIT 1) a ON true
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE n.nspname LIKE 'src\_%' AND c.relkind IN ('r', 'p') AND c.relname NOT LIKE '\_%'
ORDER BY 1, 2"""

DB_UNUSED_INDEXES_SQL = """
SELECT n.nspname || '.' || ic.relname AS index, n.nspname || '.' || c.relname AS "table",
       pg_relation_size(ic.oid) AS bytes, am.amname AS method
FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = s.indexrelid
JOIN pg_class ic ON ic.oid = s.indexrelid JOIN pg_class c ON c.oid = s.relid
JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_am am ON am.oid = ic.relam
WHERE s.idx_scan = 0 AND NOT i.indisprimary AND NOT i.indisunique AND pg_relation_size(ic.oid) > 1048576
ORDER BY 3 DESC LIMIT 25"""

# Any envelope works for the plan; this one is downtown Portland, Maine.
PLAN_PROBE = "ST_MakeEnvelope(-70.27, 43.65, -70.24, 43.67, 4326)"
_db_cache: dict[str, Any] = {"at": 0.0, "data": None}


def _view_plan_uses_index(conn, name: str, geom: str) -> tuple[bool | None, str | None]:
    """Plan the tile filter with sequential scans disabled: if no index appears, none can be used."""
    q = sql.SQL("EXPLAIN SELECT 1 FROM {} WHERE {} && " + PLAN_PROBE).format(sql.Identifier("pub", name), sql.Identifier(geom))
    try:
        with conn.transaction():
            conn.execute("SET LOCAL enable_seqscan = off")
            conn.execute("SET LOCAL statement_timeout = '5s'")
            plan = "\n".join(r["QUERY PLAN"] for r in conn.execute(q).fetchall())
    except Exception as e:  # noqa: BLE001  a broken view is reported, not fatal
        return None, str(e).splitlines()[0]
    return bool(re.search(r"Index Scan|Index Only Scan|Bitmap Index Scan", plan)), None


def _table_issues(t: dict) -> list[dict]:
    out = []
    big = (t["rows"] or 0) >= 1000
    if t["geom"] and not t["spatial_index"] and big:
        out.append({"level": "fail", "code": "no_spatial_index", "message": "geometry column has no spatial (GiST) index"})
    if t["geom"] and (t["geometry_type"] or "").lower() == "geometry":
        out.append({"level": "warn", "code": "generic_geometry",
                    "message": "untyped geometry column: views must cast it, which hides the index (re-import to normalize)"})
    if t["geom"] and (t["dims"] or 2) > 2:
        out.append({"level": "warn", "code": "zm_geometry",
                    "message": f"{t['dims']}D geometry (Z/M values): views must ST_Force2D it, which hides the index"})
    if t["last_analyzed"] is None and big:
        out.append({"level": "warn", "code": "never_analyzed", "message": "never analyzed: the planner is guessing row counts"})
    live, dead = t["n_live_tup"] or 0, t["n_dead_tup"] or 0
    if live >= 10000 and dead > 0.2 * live:
        out.append({"level": "warn", "code": "dead_rows", "message": f"{dead:,} dead rows ({dead / live:.0%}): needs VACUUM"})
    return out


@app.get("/api/admin/database", dependencies=[Depends(require_admin)])
def database_health(refresh: bool = False) -> dict:
    """Index and table health for /admin/database. Cached for a minute (it plans every pub view)."""
    if not refresh and _db_cache["data"] and time.monotonic() - _db_cache["at"] < 60:
        return _db_cache["data"]
    # Catalog and statistics views are readable by admin_api; planning a pub view needs app_rw, which reads pub.
    with projects_pool.connection() as conn:
        views = conn.execute(DB_VIEWS_SQL).fetchall()
        for v in views:
            v["sources"] = sorted(v["sources"] or [])
            v["spatial_index_usable"], v["error"] = _view_plan_uses_index(conn, v["name"], v["geom"])
    with pool.connection() as conn:
        tables = conn.execute(DB_TABLES_SQL).fetchall()
        unused = conn.execute(DB_UNUSED_INDEXES_SQL).fetchall()
        meta = conn.execute("SELECT pg_database_size(current_database()) AS db_bytes, "
                            "(SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()) AS stats_since, "
                            "now() AS checked_at").fetchone()
    for t in tables:
        t["issues"] = _table_issues(t)
    view_fail = [v for v in views if v["spatial_index_usable"] is not True]
    data = {
        **meta,
        "summary": {
            "views": len(views), "views_indexed": len(views) - len(view_fail),
            "tables": len(tables), "tables_with_issues": sum(1 for t in tables if t["issues"]),
            "unused_index_bytes": sum(u["bytes"] for u in unused),
        },
        "views": views, "tables": tables, "unused_indexes": unused,
    }
    _db_cache.update(at=time.monotonic(), data=data)
    return data


@app.get("/api/admin/datasets", dependencies=[Depends(require_admin)])
def list_datasets() -> dict:
    datasets = rows(DATASETS_SQL + " ORDER BY r.group_name NULLS LAST, r.name")
    for d in datasets:
        d["status"] = dataset_status(d)
    adhoc = rows(
        f"""SELECT kind, locator, row_count, bytes, health, health_detail, imported_at, source,
                   {BBOX.format(b="bbox")} AS bbox
            FROM app.dataset_outputs WHERE recipe_name IS NULL ORDER BY locator""")
    return {"datasets": datasets, "adhoc": adhoc}


@app.get("/api/admin/datasets/{name}", dependencies=[Depends(require_admin)])
def get_dataset(name: str) -> dict:
    d = one(DATASETS_SQL + " WHERE r.name = %s", (name,))
    if not d:
        raise HTTPException(404, f"no dataset named {name}")
    d["status"] = dataset_status(d)
    extra = one("SELECT upstream, outputs AS declared_outputs, freshness AS freshness_spec, parts AS parts_spec, "
                "todo, yaml_path, yaml_text, yaml_sha256 FROM app.recipes WHERE name = %s", (name,))
    d.update(extra or {})
    d["outputs"] = rows(
        f"""SELECT id, kind, locator, public_url, projects, source, source_srs, target_srs, geometry_type, srid,
                   row_count, invalid_geom_count, raster, bytes, checksum, loaded_vintage, loaded_run_id,
                   imported_at, imported_by, notes, health, health_detail, health_checked_at,
                   {BBOX.format(b="bbox")} AS bbox
            FROM app.dataset_outputs WHERE recipe_name = %s
            ORDER BY array_position(ARRAY['postgis_table','pub_view','materialized_view','tipg_collection','cog','tile_url'], kind), locator""",
        (name,))
    d["parts"] = rows(
        """SELECT part_key, part_kind, upstream_version, upstream_date, upstream_etag, upstream_last_modified,
                  upstream_bytes, loaded_version, loaded_date, loaded_run_id, checksum, bytes, row_count,
                  status, status_detail, checked_at
           FROM app.dataset_parts WHERE recipe_name = %s ORDER BY part_key""", (name,))
    d["freshness_checks"] = rows(
        "SELECT method, verdict, detail, observed, checked_at FROM app.freshness_checks "
        "WHERE recipe_name = %s ORDER BY checked_at DESC LIMIT 10", (name,))
    d["keys"] = rows(
        "SELECT key_name, configured, fingerprint, last_used_ok_at, last_error_at, reported_at "
        "FROM app.secrets_status WHERE key_name = ANY(%s) ORDER BY key_name", (d.get("requires_keys") or [],))
    d["active_jobs"] = rows(
        """SELECT id, action, status, progress_message, attempts, max_attempts, run_after, created_by, created_at
           FROM app.jobs WHERE recipe_name = %s AND kind = 'dataset' AND status IN ('queued', 'running', 'cancel_requested')
             AND coalesce(locked_by, '') NOT LIKE 'inline@%%' ORDER BY id""", (name,))
    d["runs"] = rows(
        """SELECT id, action, status, outcome, triggered_by, started_at, finished_at,
                  extract(epoch FROM duration)::float8 AS seconds, rows_written, bytes_downloaded, error
           FROM app.runs WHERE recipe_name = %s ORDER BY id DESC LIMIT 50""", (name,))
    return d


@app.get("/api/admin/datasets/{name}/coverage.geojson", dependencies=[Depends(require_admin)])
def dataset_coverage(name: str) -> JSONResponse:
    """requested (outline), received (fill), missing, and per-part footprints with their status."""
    fc = one(
        """SELECT json_build_object('type', 'FeatureCollection', 'features', COALESCE(json_agg(f), '[]'::json)) AS fc
           FROM (
             SELECT json_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(g, 5)::json,
                                      'properties', json_build_object('role', role, 'status', status, 'key', key)) AS f
             FROM (
               SELECT 'requested' AS role, NULL AS status, NULL AS key, requested_geom AS g FROM app.coverages WHERE recipe_name = %(n)s
               UNION ALL SELECT 'received', NULL, NULL, received_geom FROM app.coverages WHERE recipe_name = %(n)s
               UNION ALL SELECT 'missing', NULL, NULL, missing_geom FROM app.coverages WHERE recipe_name = %(n)s
               UNION ALL SELECT 'part', status, part_key, footprint FROM app.dataset_parts WHERE recipe_name = %(n)s
             ) x WHERE g IS NOT NULL
           ) y""", {"n": name})
    return JSONResponse(fc["fc"] if fc else {"type": "FeatureCollection", "features": []},
                        media_type="application/geo+json")


@app.get("/api/admin/runs", dependencies=[Depends(require_admin)])
def list_runs(limit: int = 100) -> list[dict]:
    return rows(
        """SELECT id, recipe_name, action, status, outcome, triggered_by, started_at, finished_at,
                  extract(epoch FROM duration)::float8 AS seconds, rows_written, bytes_downloaded
           FROM app.runs ORDER BY id DESC LIMIT %s""", (min(max(limit, 1), 500),))


@app.get("/api/admin/runs/{run_id}", dependencies=[Depends(require_admin)])
def get_run(run_id: int) -> dict:
    r = one("""SELECT r.*, extract(epoch FROM r.duration)::float8 AS seconds, j.status AS job_status, j.created_by AS job_created_by
               FROM app.runs r LEFT JOIN app.jobs j ON j.id = r.job_id WHERE r.id = %s""", (run_id,))
    if not r:
        raise HTTPException(404, f"no run {run_id}")
    r.pop("duration", None)
    return r


@app.get("/api/admin/jobs", dependencies=[Depends(require_admin)])
def list_jobs(limit: int = 100) -> list[dict]:
    return rows(
        """SELECT j.id, j.recipe_name, j.action, j.status, j.concurrency_class, j.attempts, j.max_attempts,
                  j.locked_by, j.created_by, j.created_at, j.heartbeat_at, j.finished_at,
                  j.kind, j.process_id, j.inputs, j.progress::float8 AS progress, j.progress_message,
                  (SELECT max(r.id) FROM app.runs r WHERE r.job_id = j.id) AS run_id
           FROM app.jobs j ORDER BY j.id DESC LIMIT %s""", (min(max(limit, 1), 500),))


@app.get("/api/admin/keys", dependencies=[Depends(require_admin)])
def list_keys() -> list[dict]:
    """Which external API keys are configured for the processes that use them. Never the values."""
    return rows("SELECT key_name, configured, fingerprint, required_by, last_used_ok_at, last_error_at, reported_at "
                "FROM app.secrets_status ORDER BY key_name")


# ---- projects (Phase 3) ------------------------------------------------------------------------
# Public reads for the hub and viewer; writes, validation and field stats are admin-only (the /admin/new wizard).

COLLECTION = re.compile(r"^pub\.[a-z0-9_]+$")
COG = re.compile(r"^[a-z0-9_/-]+$")


def _admin_user(request: Request) -> str:
    user = base64.b64decode(request.headers["authorization"][6:].strip()).decode().partition(":")[0]
    return f"admin:{user}"


def _cog_exists(name: str) -> bool:
    if not COG.match(name):
        return False
    try:
        with urllib.request.urlopen(f"{TITILER}/cog/info?url={COG_ROOT}/{name}.tif", timeout=10) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def _summary(p: dict) -> dict:
    m = json.loads(p["manifest"])
    return {
        "slug": p["slug"], "title": m["title"], "status": m["status"], "description": m.get("description", ""),
        "tags": m.get("tags", []), "layerCount": len(m["layers"]),
        "pendingLayers": [{"title": l["title"], "todo": l.get("todo") or "Not configured yet."}
                          for l in m["layers"] if l.get("status") == "todo"],
        "notes": m.get("notes", []), "version": p["version"], "updatedAt": p["updated_at"],
        "valid": bool((p["validation"] or {}).get("ok", True)),
    }


# ---- public site: only published projects -----------------------------------------------------------------
# In production the public listener of the proxy stamps every request with `X-Public-Site: 1` (overwriting anything
# a client sends); the admin-only listener (localhost, SSH tunnel) strips it. On the public site only projects with
# status `ready` exist: the hub, the viewer, charts and reports all 404 for drafts and stubs.

def _public(request: Request) -> bool:
    return request.headers.get("x-public-site") == "1"


def _project_visible(conn, request: Request, slug: str) -> bool:
    sql_ = "SELECT 1 FROM app.projects WHERE slug = %s" + (" AND status = 'ready'" if _public(request) else "")
    return conn.execute(sql_, (slug,)).fetchone() is not None


@app.get("/api/projects")
def list_projects(request: Request, response: Response) -> dict:
    with projects_pool.connection() as conn:
        ps = conn.execute("SELECT slug, manifest::text AS manifest, version, updated_at, validation FROM app.projects "
                          + ("WHERE status = 'ready' " if _public(request) else "")
                          + "ORDER BY position, slug").fetchall()
    response.headers["Cache-Control"] = "no-cache"
    return {"projects": [_summary(p) for p in ps]}


@app.get("/api/projects/{slug}")
def get_project(slug: str, request: Request) -> Response:
    """The manifest exactly as stored (json keeps key order), for the viewer and `mapgen export`."""
    with projects_pool.connection() as conn:
        p = conn.execute("SELECT manifest::text AS manifest FROM app.projects WHERE slug = %s"
                         + (" AND status = 'ready'" if _public(request) else ""), (slug,)).fetchone()
    if not p:
        raise HTTPException(404, f"no project {slug}")
    return Response(p["manifest"], media_type="application/json", headers={"Cache-Control": "no-cache"})


async def _manifest_body(request: Request) -> Any:
    body = await request.body()
    if len(body) > MAX_MANIFEST_BYTES:
        raise HTTPException(413, "manifest too large")
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"body is not JSON: {e}") from None


def _validate(m: Any, slug: str | None = None) -> dict:
    with projects_pool.connection() as conn:
        return V.validate(m, slug, conn=conn, cog_exists=_cog_exists)


@app.post("/api/admin/projects/validate", dependencies=[Depends(require_admin_or_pipeline)])
async def validate_project(request: Request) -> dict:
    return _validate(await _manifest_body(request))


def _save(m: dict, rep: dict, who: str, *, create: bool) -> dict:
    text = V.normalize(m)
    digest = hashlib.sha256(text.encode()).hexdigest()
    with projects_pool.connection() as conn, conn.transaction():
        cur = conn.execute("SELECT version, checksum FROM app.projects WHERE slug = %s FOR UPDATE", (m["slug"],)).fetchone()
        if create and cur:
            raise HTTPException(409, f"project {m['slug']} already exists")
        if not create and not cur:
            raise HTTPException(404, f"no project {m['slug']}")
        if cur and cur["checksum"] == digest:
            return {"slug": m["slug"], "version": cur["version"], "result": "unchanged", "report": rep}
        version = cur["version"] + 1 if cur else 1
        conn.execute(
            """INSERT INTO app.projects (slug, title, status, position, manifest, checksum, version, origin, validation,
                                         updated_at, updated_by)
               VALUES (%(slug)s, %(title)s, %(status)s,
                       (SELECT coalesce(max(position), -1) + 1 FROM app.projects), %(m)s::json, %(sum)s, %(v)s, 'api',
                       %(rep)s, now(), %(who)s)
               ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title, status = EXCLUDED.status,
                   manifest = EXCLUDED.manifest, checksum = EXCLUDED.checksum, version = EXCLUDED.version,
                   origin = 'api', validation = EXCLUDED.validation, updated_at = now(), updated_by = EXCLUDED.updated_by""",
            {"slug": m["slug"], "title": m["title"], "status": m["status"], "m": text, "sum": digest, "v": version,
             "rep": json.dumps(rep), "who": who})
        conn.execute("INSERT INTO app.manifest_versions (slug, version, manifest, checksum, origin, created_by) "
                     "VALUES (%s, %s, %s::json, %s, 'api', %s)", (m["slug"], version, text, digest, who))
    return {"slug": m["slug"], "version": version, "result": "created" if create else "updated", "report": rep}


@app.post("/api/admin/projects", dependencies=[Depends(require_admin)], status_code=201)
async def create_project(request: Request) -> dict:
    m = await _manifest_body(request)
    rep = _validate(m)
    if not rep["ok"]:
        raise HTTPException(422, rep)
    return _save(m, rep, _admin_user(request), create=True)


@app.put("/api/admin/projects/{slug}", dependencies=[Depends(require_admin)])
async def update_project(slug: str, request: Request) -> dict:
    m = await _manifest_body(request)
    rep = _validate(m, slug)
    if not rep["ok"]:
        raise HTTPException(422, rep)
    return _save(m, rep, _admin_user(request), create=False)


@app.get("/api/admin/projects", dependencies=[Depends(require_admin)])
def admin_list_projects() -> list[dict]:
    """Every registered project with where it is managed: origin 'file' (projects/<slug>/, git) or 'api' (wizard)."""
    with projects_pool.connection() as conn:
        ps = conn.execute(
            """SELECT p.slug, p.title, p.status, p.origin, p.version, p.updated_at, p.updated_by,
                      coalesce((p.validation->>'ok')::boolean, true) AS valid,
                      json_array_length(p.manifest->'layers') AS layers
               FROM app.projects p ORDER BY p.position, p.slug""").fetchall()
    return ps


@app.delete("/api/admin/projects/{slug}", dependencies=[Depends(require_admin)], status_code=204)
def delete_project(slug: str) -> Response:
    """Remove a project saved in the wizard. File-managed projects come back on the next `mapgen sync`,
    so they are refused here: remove them from projects/index.json instead."""
    with projects_pool.connection() as conn, conn.transaction():
        p = conn.execute("SELECT origin FROM app.projects WHERE slug = %s FOR UPDATE", (slug,)).fetchone()
        if not p:
            raise HTTPException(404, f"no project {slug}")
        if p["origin"] != "api":
            raise HTTPException(409, f"{slug} is managed by projects/{slug}/project.json; remove it there")
        conn.execute("DELETE FROM app.projects WHERE slug = %s", (slug,))
    return Response(status_code=204)


def _collection(collection: str) -> tuple[str, str]:
    if not COLLECTION.match(collection):
        raise HTTPException(400, "collection must look like pub.<name>")
    return "pub", collection.split(".", 1)[1]


@app.get("/api/admin/projects/fields", dependencies=[Depends(require_admin_or_pipeline)])
def collection_fields(collection: str) -> dict:
    """Columns of a pub view (for the wizard's field pickers) and its geometry type."""
    schema, name = _collection(collection)
    with projects_pool.connection() as conn:
        cols = conn.execute(
            """SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
                      CASE WHEN a.atttypid = 'geometry'::regtype THEN postgis_typmod_type(a.atttypmod) END AS geometry
               FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
               WHERE c.relnamespace = 'pub'::regnamespace AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
               ORDER BY a.attnum""", (name,)).fetchall()
    if not cols:
        raise HTTPException(404, f"no view {collection}")
    geom = next((c["geometry"] for c in cols if c["geometry"]), None)
    numeric = ("integer", "bigint", "smallint", "numeric", "real", "double precision")
    return {"collection": collection, "geometry": geom,
            "fields": [{"name": c["name"], "type": c["type"],
                        "numeric": c["type"].split("(")[0] in numeric}
                       for c in cols if not c["geometry"]]}


@app.get("/api/admin/projects/stats", dependencies=[Depends(require_admin_or_pipeline)])
def field_stats(collection: str, field: str, k: int = 5) -> dict:
    """Breaks for a numeric field (quantiles), or the most common values of a text field, for style presets."""
    schema, name = _collection(collection)
    fields = {f["name"]: f for f in collection_fields(collection)["fields"]}
    if field not in fields:
        raise HTTPException(404, f"{collection} has no field {field}")
    k = min(max(k, 2), 9)
    rel, col = sql.Identifier(schema, name), sql.Identifier(field)
    with projects_pool.connection() as conn:
        if fields[field]["numeric"]:
            fractions = [i / k for i in range(1, k)]
            r = conn.execute(sql.SQL(
                "SELECT count(*) AS count, count({c}) AS non_null, min({c})::float8 AS min, max({c})::float8 AS max, "
                "percentile_disc(%s::float8[]) WITHIN GROUP (ORDER BY {c})::float8[] AS breaks FROM {r}").format(c=col, r=rel),
                (fractions,)).fetchone()
            return {"field": field, "kind": "numeric", **r}
        r = conn.execute(sql.SQL(
            "SELECT {c}::text AS value, count(*) AS count FROM {r} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 13").format(c=col, r=rel)
        ).fetchall()
        return {"field": field, "kind": "categorical", "values": r[:12], "more": len(r) > 12}


# ---- charts: D3 data computed on the fly (plan: project-builder §1.5) ----------------------------------------
# Public like the maps themselves, but only for charts declared in a saved manifest: the chart's fields are checked
# against the view and enter SQL as identifiers; the aggregate comes from a fixed list. `bbox` limits the chart to
# the map view; `data.within` to one place (e.g. a design's town). Results are cached for two minutes.

CHART_AGG = {"count": "count(*)", "sum": "sum({v})", "avg": "avg({v})", "min": "min({v})", "max": "max({v})",
             "median": "percentile_cont(0.5) WITHIN GROUP (ORDER BY {v})"}
CHART_TTL = 120.0
_chart_cache: dict[tuple, tuple[float, dict]] = {}


def _chart_agg(agg: str, field: str | None) -> sql.Composable:
    if agg == "count" or not field:
        return sql.SQL("count(*)")
    return sql.SQL("(" + CHART_AGG[agg] + ")::float8").format(v=sql.Identifier(field))


def _chart_where(conn, data: dict, bbox: list[float] | None) -> tuple[sql.Composable, list]:
    parts, params = [sql.SQL("TRUE")], []
    if bbox:
        parts.append(sql.SQL("t.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)"))
        params += bbox
    w = data.get("within")
    if w:
        u = _unit(conn, w["unit"])
        # A feature belongs to the place when a point on its surface lies inside: neighbours that only touch the
        # boundary are not counted. The place geometry is a scalar subquery (evaluated once), so `t.geom && ...`
        # becomes an index search on the feature table instead of a probe of the place per feature.
        place = sql.SQL("(SELECT p.geom FROM {u} p WHERE p.unit_key = %s LIMIT 1)").format(
            u=sql.Identifier("pub", u["collection"].split(".", 1)[1]))
        parts.append(sql.SQL("t.geom && {g} AND ST_Intersects({g}, ST_PointOnSurface(t.geom))").format(g=place))
        params += [str(w["place"]), str(w["place"])]
    return sql.SQL(" AND ").join(parts), params


def _chart_data(conn, chart: dict, bbox: list[float] | None) -> dict:
    data = chart["data"]
    cols = V.chart_columns(conn, data["collection"])
    if cols is None or "geom" not in cols:
        raise HTTPException(409, f"{data['collection']} is missing or has no geom column")
    for k in ("category", "value", "x", "y", "label"):
        if data.get(k) and data[k] not in cols:
            raise HTTPException(409, f"{data['collection']} has no column {data[k]!r}")
    rel = sql.Identifier("pub", data["collection"].split(".", 1)[1])
    where, params = _chart_where(conn, data, bbox)
    kind = chart["type"]
    if kind in ("bar", "donut"):
        agg = data.get("agg", "count")
        limit = data.get("limit", 12 if kind == "bar" else 8)
        rows = conn.execute(sql.SQL(
            "SELECT {c}::text AS category, {a} AS value, count(*) AS n FROM {r} t WHERE {w} AND {c} IS NOT NULL "
            "GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 500").format(
            c=sql.Identifier(data["category"]), a=_chart_agg(agg, data.get("value")), r=rel, w=where), params).fetchall()
        top, rest = rows[:limit], rows[limit:]
        if rest and agg in ("count", "sum"):
            top.append({"category": f"Other ({len(rest)})", "value": sum(r["value"] or 0 for r in rest),
                        "n": sum(r["n"] for r in rest), "other": True})
        return {"rows": top, "n": sum(r["n"] for r in rows), "groups": len(rows)}
    if kind == "histogram":
        v = sql.Identifier(data["value"])
        s = conn.execute(sql.SQL(
            "SELECT count({v}) AS n, min({v})::float8 AS min, max({v})::float8 AS max, "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY {v})::float8 AS median, "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY {v})::float8 AS p95 FROM {r} t WHERE {w}").format(
            v=v, r=rel, w=where), params).fetchone()
        if not s["n"] or s["min"] is None:
            return {"bins": [], **s}
        k, lo, hi = data.get("bins", 12), s["min"], s["max"]
        # A long tail (max more than 3x the 95th percentile) would squeeze everything into the first bin: bin up to
        # the 95th percentile and let the last bin hold "and over".
        s["open_end"] = bool(s["p95"] is not None and s["p95"] > lo and hi > 3 * s["p95"])
        if s["open_end"]:
            hi = s["p95"]
        width = (hi - lo) / k or 1.0
        counts = {r["b"]: r["n"] for r in conn.execute(sql.SQL(
            "SELECT least(width_bucket({v}::float8, %s, %s, %s), %s) AS b, count(*) AS n FROM {r} t "
            "WHERE {w} AND {v} IS NOT NULL GROUP BY 1").format(v=v, r=rel, w=where),
            [lo, lo + width * k, k, k, *params]).fetchall()}
        return {"bins": [{"x0": lo + width * (b - 1), "x1": lo + width * b, "count": counts.get(b, 0)} for b in range(1, k + 1)], **s}
    if kind == "scatter":
        x, y = sql.Identifier(data["x"]), sql.Identifier(data["y"])
        label = sql.Identifier(data["label"]) if data.get("label") else sql.SQL("NULL")
        pts = conn.execute(sql.SQL(
            "SELECT t.id, {x}::float8 AS x, {y}::float8 AS y, {l}::text AS label FROM {r} t "
            "WHERE {w} AND {x} IS NOT NULL AND {y} IS NOT NULL ORDER BY t.id LIMIT 3000").format(
            x=x, y=y, l=label, r=rel, w=where), params).fetchall()
        r = conn.execute(sql.SQL("SELECT corr({x}::float8, {y}::float8) AS r, count(*) AS n FROM {r} t "
                                 "WHERE {w} AND {x} IS NOT NULL AND {y} IS NOT NULL").format(
            x=x, y=y, r=rel, w=where), params).fetchone()
        return {"points": pts, **r}
    # stats: one row of headline numbers
    stats = data.get("stats") or []
    for st in stats:
        if st.get("value") and st["value"] not in cols:
            raise HTTPException(409, f"{data['collection']} has no column {st['value']!r}")
    row = conn.execute(sql.SQL("SELECT {cols} FROM {r} t WHERE {w}").format(
        cols=sql.SQL(", ").join(sql.SQL("{a} AS {n}").format(a=_chart_agg(st.get("agg", "count"), st.get("value")),
                                                            n=sql.Identifier(f"s{i}")) for i, st in enumerate(stats)),
        r=rel, w=where), params).fetchone()
    return {"stats": [{"label": st["label"], "value": row[f"s{i}"], "format": st.get("format", chart.get("format"))}
                      for i, st in enumerate(stats)]}


@app.get("/api/projects/{slug}/charts/{chart_id}")
def project_chart(slug: str, chart_id: str, request: Request, bbox: str | None = None) -> dict:
    """Data for one of a project's charts; `bbox=w,s,e,n` limits it to the map view."""
    box = None
    if bbox:
        try:
            box = [round(float(v), 4) for v in bbox.split(",")]
        except ValueError:
            box = []
        if len(box) != 4 or not (-180 <= box[0] < box[2] <= 180 and -90 <= box[1] < box[3] <= 90):
            raise HTTPException(400, "bbox must be w,s,e,n in degrees")
    with projects_pool.connection() as conn:
        p = conn.execute("SELECT manifest, version FROM app.projects WHERE slug = %s"
                         + (" AND status = 'ready'" if _public(request) else ""), (slug,)).fetchone()
        if not p:
            raise HTTPException(404, f"no project {slug}")
        chart = next((c for c in p["manifest"].get("charts") or [] if c.get("id") == chart_id), None)
        if not chart:
            raise HTTPException(404, f"project {slug} has no chart {chart_id!r}")
        key = (slug, p["version"], chart_id, tuple(box or ()))
        hit = _chart_cache.get(key)
        if hit and time.monotonic() - hit[0] < CHART_TTL:
            return hit[1]
        out = {"chart": chart_id, "type": chart["type"], "scope": "view" if box else "all", **_chart_data(conn, chart, box)}
    if len(_chart_cache) > 500:
        _chart_cache.clear()
    _chart_cache[key] = (time.monotonic(), out)
    return out


# ---- PDF reports (plan: project-builder §1.6) -----------------------------------------------------------------
# Admins queue a `report` job; the reporter service prints /p/<slug>/report to data/reports/<slug>/<job>.pdf and
# records it in app.reports. Listing and downloading are public, like the maps they describe.

REPORTS_DIR = Path(os.environ.get("REPORTS_DIR", "/reports"))
REPORT_COLUMNS = "id, slug, job_id, path, bytes, pages, manifest_version, created_at, created_by"


def _report_out(r: dict) -> dict:
    return {**r, "url": f"/api/projects/{r['slug']}/reports/{r['id']}.pdf"}


@app.post("/api/admin/projects/{slug}/reports", dependencies=[Depends(require_admin)], status_code=201)
def queue_report(slug: str, request: Request, response: Response) -> dict:
    """Queue a PDF report of one project (deduplicated while one is queued or running)."""
    with projects_pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM app.projects WHERE slug = %s", (slug,)).fetchone():
            raise HTTPException(404, f"no project {slug}")
        key = f"report:{slug}"
        row = conn.execute(
            f"""INSERT INTO app.jobs (kind, action, params, concurrency_class, max_attempts, dedupe_key, created_by)
                VALUES ('report', 'render', %s, 'report', 2, %s, %s)
                ON CONFLICT (dedupe_key) WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL DO NOTHING
                RETURNING {JOB_COLUMNS}""", (json.dumps({"slug": slug}), key, _caller(request))).fetchone()
        if row is None:
            row = conn.execute(f"SELECT {JOB_COLUMNS} FROM app.jobs WHERE dedupe_key = %s AND status IN ('queued', 'running')",
                               (key,)).fetchone()
            response.status_code = 200
            row["deduplicated"] = True
    return row


@app.get("/api/projects/{slug}/reports")
def list_reports(slug: str, request: Request) -> list[dict]:
    with projects_pool.connection() as conn:
        if not _project_visible(conn, request, slug):
            raise HTTPException(404, f"no project {slug}")
        return [_report_out(r) for r in conn.execute(
            f"SELECT {REPORT_COLUMNS} FROM app.reports WHERE slug = %s ORDER BY created_at DESC LIMIT 20", (slug,)).fetchall()]


@app.get("/api/projects/{slug}/reports/{name}")
def get_report(slug: str, name: str, request: Request) -> FileResponse:
    """`<id>.pdf`, or `latest.pdf` for the newest report of the project."""
    m = re.fullmatch(r"(\d+|latest)\.pdf", name)
    if not m:
        raise HTTPException(404, "not a report")
    with projects_pool.connection() as conn:
        if not _project_visible(conn, request, slug):
            raise HTTPException(404, f"no report {name} for {slug}")
        r = conn.execute(f"SELECT {REPORT_COLUMNS} FROM app.reports WHERE slug = %s"
                         + ("" if m[1] == "latest" else " AND id = %s") + " ORDER BY created_at DESC LIMIT 1",
                         (slug,) if m[1] == "latest" else (slug, int(m[1]))).fetchone()
    path = (REPORTS_DIR / r["path"]).resolve() if r else None
    if not r or not path.is_relative_to(REPORTS_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, f"no report {name} for {slug}")
    stamp = r["created_at"].strftime("%Y-%m-%d")
    return FileResponse(path, media_type="application/pdf", filename=f"{slug}-report-{stamp}.pdf",
                        content_disposition_type="inline")


# ---- project builder: units, places, map designs (plan: project-builder §1.1, §1.7) -------------------------
# Admin only. A design (templates/designs/<id>.json) + a place (one row of a pub.units__* view) -> a finished
# manifest: curated layers copied from the registered projects, a focus mask/outline, framing and titles. Nothing
# is written here; the page saves the manifest through POST /api/admin/projects like the wizard does.

DESIGNS_DIR = Path(os.environ.get("DESIGNS_DIR", "/designs"))
UNIT_COLUMNS = ("id, title, plural, description, collection, position, study_area, max_units_without_study_area, "
                "minzoom, unit_count, attributes, attribution")
DESIGN_OVERRIDES = ("visible", "opacity", "minzoom", "maxzoom", "title", "group")


def _units(conn) -> dict[str, dict]:
    return {u["id"]: u for u in conn.execute(f"SELECT {UNIT_COLUMNS} FROM app.units ORDER BY position DESC").fetchall()}


def _unit(conn, unit: str) -> dict:
    u = _units(conn).get(unit)
    if not u:
        raise HTTPException(404, f"no unit {unit!r}")
    return u


def _designs() -> dict[str, dict]:
    out = {}
    for f in sorted(DESIGNS_DIR.glob("*.json")):
        d = json.loads(f.read_text())
        out[d["id"]] = d
    return out


PLACE_COLUMNS = ("unit_key AS key, name, short_name, county_name, county_geoid, "
                 "ARRAY[ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom)]::float8[] AS bbox")


@app.get("/api/admin/units", dependencies=[Depends(require_admin)])
def list_units() -> list[dict]:
    with projects_pool.connection() as conn:
        return list(_units(conn).values())


@app.get("/api/admin/units/{unit}/places", dependencies=[Depends(require_admin)])
def unit_places(unit: str, q: str = "", county: str | None = None, limit: int = 25) -> list[dict]:
    """Search one unit by name (or exact key), for the place picker. Names starting with q come first."""
    q = q.strip()
    with projects_pool.connection() as conn:
        u = _unit(conn, unit)
        if u["unit_count"] > 5000 and len(q) < 2 and not county:
            raise HTTPException(400, f"{u['plural']}: type at least two letters, or choose a county")
        where, params = [sql.SQL("TRUE")], []
        if q:
            where.append(sql.SQL("(name ILIKE %s OR unit_key = %s)"))
            params += [f"%{q}%", q]
        if county:
            where.append(sql.SQL("county_geoid = %s"))
            params.append(county)
        query = sql.SQL("SELECT {cols} FROM {rel} WHERE {where} ORDER BY (short_name ILIKE %s) DESC, short_name, name LIMIT %s").format(
            cols=sql.SQL(PLACE_COLUMNS), rel=sql.Identifier("pub", u["collection"].split(".", 1)[1]),
            where=sql.SQL(" AND ").join(where))
        return conn.execute(query, [*params, f"{q}%", min(max(limit, 1), 100)]).fetchall()


@app.get("/api/admin/designs", dependencies=[Depends(require_admin)])
def list_designs() -> list[dict]:
    return [{k: d.get(k) for k in ("id", "title", "description", "geographies")} for d in _designs().values()]


def _focus_layer(unit: str, place: dict) -> dict:
    """Soft veil over everything outside the place, and its outline (pub.units__focus)."""
    part = lambda p: ["==", ["get", "part"], p]  # noqa: E731
    return {
        "id": "focus",
        "title": f"{place['short_name']} boundary",
        "group": "Focus",
        "source": {"type": "tipg-vector", "collection": "pub.units__focus", "params": {"unit": unit, "place": place["key"]}},
        "style": {"kind": "maplibre", "layers": [
            {"type": "fill", "filter": part("mask"), "paint": {"fill-color": "#f7f7f5", "fill-opacity": 0.62}},
            {"type": "line", "filter": part("outline"), "paint": {"line-color": "#ffffff", "line-width": 6, "line-opacity": 0.85}},
            {"type": "line", "filter": part("outline"), "paint": {"line-color": "#1d3557", "line-width": 2.2}},
        ]},
        "legend": {"type": "single", "color": "#1d3557", "label": place["name"]},
        "interaction": {"inspect": False},
        "visible": True,
    }


def _framing(bbox: list[float], padding: float, basemap: str) -> dict:
    w, s, e, n = bbox
    dx, dy = (e - w) * padding, (n - s) * padding
    b = [round(w - dx, 5), round(s - dy, 5), round(e + dx, 5), round(n + dy, 5)]
    span = max(b[2] - b[0], (b[3] - b[1]) * 1.4, 1e-4)  # degrees of latitude are taller in Web Mercator at 45° N
    zoom = round(min(max(math.log2(360 / span) - 0.3, 4), 16), 1)
    return {"center": [round((b[0] + b[2]) / 2, 5), round((b[1] + b[3]) / 2, 5)], "zoom": zoom, "bounds": b,
            "basemap": basemap}


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48].strip("-")


@app.post("/api/admin/designs/{design_id}/manifest", dependencies=[Depends(require_admin)])
async def design_manifest(design_id: str, request: Request) -> dict:
    """Build (not save) the manifest for one design and place: {unit, place, title?, slug?} -> {manifest, report}."""
    d = _designs().get(design_id)
    if not d:
        raise HTTPException(404, f"no design {design_id!r}")
    body = await request.json()
    unit, key = body.get("unit"), str(body.get("place") or "")
    if unit not in d["geographies"]:
        raise HTTPException(422, f"the {d['title']} design is for {', '.join(d['geographies'])}, not {unit!r}")
    refs = [i["ref"][unit] if isinstance(i["ref"], dict) else i["ref"] for i in d["layers"] if "ref" in i]
    with projects_pool.connection() as conn:
        u = _unit(conn, unit)
        place = conn.execute(sql.SQL("SELECT {cols} FROM {rel} WHERE unit_key = %s").format(
            cols=sql.SQL(PLACE_COLUMNS), rel=sql.Identifier("pub", u["collection"].split(".", 1)[1])), (key,)).fetchone()
        if not place:
            raise HTTPException(404, f"no {u['title'].lower()} with key {key!r}")
        sources = {r["slug"]: r["manifest"] for r in conn.execute(
            "SELECT slug, manifest FROM app.projects WHERE slug = ANY(%s)", (sorted({r.split("/")[0] for r in refs}),)).fetchall()}
        taken = {r["slug"] for r in conn.execute("SELECT slug FROM app.projects").fetchall()}

    fields = {"name": place["name"], "short_name": place["short_name"], "county_name": place["county_name"] or ""}
    fill = lambda s: s.format_map(fields)  # noqa: E731
    layers, ids, missing = [], set(), []
    for item in d["layers"]:
        if item.get("focus"):
            spec = _focus_layer(unit, place)
        else:
            ref = item["ref"][unit] if isinstance(item["ref"], dict) else item["ref"]
            slug, lid = ref.split("/", 1)
            src = next((l for l in (sources.get(slug) or {}).get("layers", []) if l["id"] == lid), None)
            if src is None or src.get("status") == "todo":
                missing.append(ref)
                continue
            spec = copy.deepcopy(src)
            spec.update({k: item[k] for k in DESIGN_OVERRIDES if k in item})
            if spec["id"] in ids:
                spec["id"] = f"{slug.removeprefix('maine-')}-{spec['id']}"
        ids.add(spec["id"])
        layers.append(spec)

    slug = _slugify(body.get("slug") or f"{place['short_name']} {d['id']}")
    base, n = slug, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    manifest = {
        "manifestVersion": 1,
        "slug": slug,
        "status": "draft",
        "title": (body.get("title") or fill(d["projectTitle"]))[:80],
        "description": fill(d.get("projectDescription", "")),
        "tags": list(dict.fromkeys(fill(t).lower() for t in d.get("tags", []))),
        "view": _framing(place["bbox"], d.get("padding", 0.06), d.get("basemap", "positron")),
        "layers": layers,
    }
    # Design charts: `"within": "place"` -> this place; `"within": "county"` -> the place's county (for units such as
    # tracts, where the interesting comparison is the county around them).
    charts = []
    for c in copy.deepcopy(d.get("charts") or []):
        w = c["data"].pop("within", None)
        if w == "place":
            c["data"]["within"] = {"unit": unit, "place": place["key"]}
        elif w == "county" and place.get("county_geoid"):
            c["data"]["within"] = {"unit": "county", "place": place["county_geoid"]}
        if c.get("layer") and c["layer"] not in ids:
            c.pop("layer")
        c["title"] = fill(c["title"])[:80]
        charts.append(c)
    if charts:
        manifest["charts"] = charts
    return {"manifest": manifest, "report": _validate(manifest), "missing_layers": missing}


# ---- analysis processes and jobs (Phase 5) -----------------------------------------------------------------
# Workers register processes (app.processes); jobs go on app.jobs (kind 'process'). Inputs are checked here against
# the descriptor and the live database before a job is queued, so workers only see well-formed work.

NUMERIC_TYPES = ("integer", "bigint", "smallint", "numeric", "real", "double precision")
JOB_COLUMNS = """id, kind, process_id, recipe_name, action, status, progress::float8 AS progress, progress_message,
                 inputs, params, result, error, concurrency_class, attempts, max_attempts, run_after, created_by,
                 created_at, started_at, finished_at,
                 (SELECT max(r.id) FROM app.runs r WHERE r.job_id = app.jobs.id) AS run_id"""


def _process(conn, process_id: str) -> dict:
    p = conn.execute("SELECT id, runtime, version, title, description, descriptor, last_seen_at FROM app.processes "
                     "WHERE id = %s", (process_id,)).fetchone()
    if not p:
        raise HTTPException(404, f"no process {process_id}")
    return p


def _relation_info(conn, collection: str) -> dict | None:
    if not COLLECTION.match(collection or ""):
        return None
    return conn.execute(
        """SELECT (SELECT postgis_typmod_type(a.atttypmod) FROM pg_attribute a WHERE a.attrelid = c.oid
                    AND a.atttypid = 'geometry'::regtype AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum LIMIT 1) AS geometry,
                  (SELECT json_object_agg(a.attname, format_type(a.atttypid, a.atttypmod)) FROM pg_attribute a
                    WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS columns
           FROM pg_class c WHERE c.relnamespace = 'pub'::regnamespace AND c.relname = %s""",
        (collection.split(".", 1)[1],)).fetchone()


def check_inputs(conn, descriptor: dict, inputs: Any) -> tuple[dict, list[dict]]:
    """Defaults filled in, and a list of {input, message} problems (empty = valid)."""
    if not isinstance(inputs, dict):
        return {}, [{"input": "(inputs)", "message": "inputs must be an object"}]
    specs = descriptor.get("inputs", {})
    errors = [{"input": k, "message": "unknown input"} for k in inputs if k not in specs]
    values = {k: inputs.get(k, spec.get("default")) for k, spec in specs.items()}
    rels: dict[str, dict | None] = {}
    for name, spec in specs.items():
        when = spec.get("when") or {}
        if any(values.get(k) != v for k, v in when.items()):
            values.pop(name, None)
            continue
        v = values.get(name)
        if v is None or v == "":
            values.pop(name, None)
            if spec.get("required"):
                errors.append({"input": name, "message": "required"})
            continue
        t = spec["type"]
        if t == "collection-ref":
            info = rels.setdefault(name, _relation_info(conn, v))
            if not info:
                errors.append({"input": name, "message": f"{v!r} is not a published view (pub.<name>)"})
            elif spec.get("geometry") and (info["geometry"] or "").lower() not in [g.lower() for g in spec["geometry"]]:
                errors.append({"input": name, "message": f"{v} has {info['geometry']} geometry; needs {', '.join(spec['geometry'])}"})
        elif t == "field-ref":
            parent = spec.get("of")
            info = rels.get(parent) or (_relation_info(conn, values.get(parent)) if values.get(parent) else None)
            cols = (info or {}).get("columns") or {}
            if not isinstance(v, str) or v not in cols:
                errors.append({"input": name, "message": f"{values.get(parent)} has no field {v!r}"})
            elif spec.get("dtype") == "numeric" and cols[v].split("(")[0] not in NUMERIC_TYPES:
                errors.append({"input": name, "message": f"{v} is {cols[v]}, not numeric"})
        elif t == "enum":
            if v not in spec.get("values", []):
                errors.append({"input": name, "message": f"must be one of {', '.join(spec.get('values', []))}"})
        elif t in ("integer", "number"):
            ok = isinstance(v, (int, float)) and not isinstance(v, bool) and (t == "number" or float(v).is_integer())
            if not ok:
                errors.append({"input": name, "message": f"must be a{'n integer' if t == 'integer' else ' number'}"})
            elif ("minimum" in spec and v < spec["minimum"]) or ("maximum" in spec and v > spec["maximum"]):
                errors.append({"input": name, "message": f"must be between {spec.get('minimum')} and {spec.get('maximum')}"})
            else:
                values[name] = int(v) if t == "integer" else float(v)
        elif t == "string" and not isinstance(v, str):
            errors.append({"input": name, "message": "must be text"})
    return values, errors


@app.get("/api/admin/processes", dependencies=[Depends(require_admin_or_analysis)])
def list_processes() -> list[dict]:
    with projects_pool.connection() as conn:
        return conn.execute("""SELECT id, runtime, version, title, description, descriptor, last_seen_at,
                                      last_seen_at > now() - interval '2 minutes' AS worker_online
                               FROM app.processes ORDER BY id""").fetchall()


@app.post("/api/admin/jobs", dependencies=[Depends(require_admin_or_analysis)], status_code=201)
async def submit_job(request: Request, response: Response) -> dict:
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("process"), str):
        raise HTTPException(400, 'body must be {"process": "<id>", "inputs": {...}}')
    with projects_pool.connection() as conn:
        proc = _process(conn, body["process"])
        values, errors = check_inputs(conn, proc["descriptor"], body.get("inputs", {}))
        if errors:
            raise HTTPException(422, {"errors": errors})
        dedupe = hashlib.sha256(json.dumps([proc["id"], values], sort_keys=True).encode()).hexdigest()
        timeout = int(proc["descriptor"].get("resources", {}).get("timeoutSec", 900))
        row = conn.execute(
            f"""INSERT INTO app.jobs (kind, action, process_id, inputs, concurrency_class, max_attempts, dedupe_key, created_by)
                VALUES ('process', 'run', %s, %s, 'analysis', 2, %s, %s)
                ON CONFLICT (dedupe_key) WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL DO NOTHING
                RETURNING {JOB_COLUMNS}""", (proc["id"], json.dumps(values), dedupe, _caller(request))).fetchone()
        if row is None:  # the same job is already queued or running
            row = conn.execute(f"SELECT {JOB_COLUMNS} FROM app.jobs WHERE dedupe_key = %s AND status IN ('queued', 'running')",
                               (dedupe,)).fetchone()
            response.status_code = 200
            row["deduplicated"] = True
    row["timeout_seconds"] = timeout
    return row


@app.get("/api/admin/jobs/{job_id}", dependencies=[Depends(require_admin_or_analysis)])
def get_job(job_id: int) -> dict:
    with projects_pool.connection() as conn:
        j = conn.execute(f"SELECT {JOB_COLUMNS} FROM app.jobs WHERE id = %s", (job_id,)).fetchone()
    if not j:
        raise HTTPException(404, f"no job {job_id}")
    return j


@app.post("/api/admin/jobs/{job_id}/cancel", dependencies=[Depends(require_admin_or_analysis)])
def cancel_job(job_id: int) -> dict:
    with projects_pool.connection() as conn:
        j = conn.execute(
            """UPDATE app.jobs SET status = CASE status WHEN 'queued' THEN 'cancelled' ELSE 'cancel_requested' END
               WHERE id = %s AND status IN ('queued', 'running') AND coalesce(locked_by, '') NOT LIKE 'inline@%%'
               RETURNING id, status""",
            (job_id,)).fetchone()
    if not j:
        raise HTTPException(409, f"job {job_id} is not queued or running")
    return j


@app.post("/api/admin/jobs/{job_id}/promote", dependencies=[Depends(require_admin)])
async def promote_job(job_id: int, request: Request) -> dict:
    """Add a finished job's layer to a project (default: analysis-sandbox), as a new registry version."""
    body = await request.json() if (await request.body()) else {}
    slug = (body or {}).get("project", "analysis-sandbox")
    with projects_pool.connection() as conn:
        j = conn.execute("SELECT status, result FROM app.jobs WHERE id = %s AND kind = 'process'", (job_id,)).fetchone()
        if not j or j["status"] != "succeeded":
            raise HTTPException(409, f"job {job_id} has not succeeded")
        p = conn.execute("SELECT manifest::text AS manifest FROM app.projects WHERE slug = %s", (slug,)).fetchone()
        if not p:
            raise HTTPException(404, f"no project {slug}")
    m = json.loads(p["manifest"])
    layer = j["result"]["layerSpec"]
    m["layers"] = [l for l in m["layers"] if l["id"] != layer["id"]] + [layer]
    rep = _validate(m, slug)
    if not rep["ok"]:
        raise HTTPException(422, rep)
    return _save(m, rep, _admin_user(request), create=False)


# ---- dataset actions (admin plan Phase B) -----------------------------------------------------------------------
# Queued as kind='dataset' jobs; the dataset worker (scripts/dataset_worker.py) runs them with scripts/geoimport.py.

DATASET_ACTIONS = ("freshness", "dry_run", "import", "redownload", "healthcheck", "enable", "disable")


def _queue_dataset_job(conn, recipe: dict, action: str, who: str) -> tuple[dict, bool]:
    job_action = "set_enabled" if action in ("enable", "disable") else action
    params = {"enabled": action == "enable"} if job_action == "set_enabled" else {}
    if job_action in ("import", "redownload"):
        cls = "raster_heavy" if recipe["kind"] == "raster" else "network"
    else:
        cls = "network" if job_action in ("freshness", "dry_run") else "db"
    attempts = {"import": 4, "redownload": 4, "freshness": 3}.get(job_action, 1)
    key = f"{'import' if job_action in ('import', 'redownload') else job_action}:{recipe['name']}"
    row = conn.execute(
        f"""INSERT INTO app.jobs (kind, recipe_name, action, params, concurrency_class, max_attempts, dedupe_key, created_by)
            VALUES ('dataset', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedupe_key) WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL DO NOTHING
            RETURNING {JOB_COLUMNS}""", (recipe["name"], job_action, json.dumps(params), cls, attempts, key, who)).fetchone()
    if row:
        return row, False
    return conn.execute(f"SELECT {JOB_COLUMNS} FROM app.jobs WHERE dedupe_key = %s AND status IN ('queued', 'running')",
                        (key,)).fetchone(), True


@app.post("/api/admin/datasets/actions", dependencies=[Depends(require_admin)])
async def dataset_action_all(request: Request) -> dict:
    """Queue one action (freshness or healthcheck) for every enabled dataset."""
    action = ((await request.json()) or {}).get("action")
    if action not in ("freshness", "healthcheck"):
        raise HTTPException(400, "action must be freshness or healthcheck")
    queued = existing = 0
    with projects_pool.connection() as conn:
        for r in conn.execute("SELECT name, kind, enabled FROM app.recipes WHERE enabled AND yaml_path IS NOT NULL "
                              "ORDER BY name").fetchall():
            _, dedup = _queue_dataset_job(conn, r, action, _admin_user(request))
            existing += dedup
            queued += not dedup
    return {"action": action, "queued": queued, "already_queued": existing}


@app.post("/api/admin/datasets/{name}/actions", dependencies=[Depends(require_admin)], status_code=201)
async def dataset_action(name: str, request: Request, response: Response) -> dict:
    body = await request.json()
    action = (body or {}).get("action")
    if action not in DATASET_ACTIONS:
        raise HTTPException(400, f"action must be one of {', '.join(DATASET_ACTIONS)}")
    with projects_pool.connection() as conn:
        r = conn.execute("SELECT name, kind, enabled, yaml_path FROM app.recipes WHERE name = %s", (name,)).fetchone()
        if not r or r["yaml_path"] is None:
            raise HTTPException(404, f"no dataset recipe {name}")
        if action in ("import", "redownload") and not r["enabled"]:
            raise HTTPException(409, f"{name} is disabled; enable it first")
        if (action == "enable" and r["enabled"]) or (action == "disable" and not r["enabled"]):
            raise HTTPException(409, f"{name} is already {'enabled' if r['enabled'] else 'disabled'}")
        job, dedup = _queue_dataset_job(conn, r, action, _admin_user(request))
    if dedup:
        response.status_code = 200
        job["deduplicated"] = True
    return job
