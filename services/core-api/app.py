"""core-api: admin backend for the dataset dashboard (plan: .claude/plans/admin-dashboard.plan.md).

Phase A is read-only. It connects as `admin_api`, which can only SELECT the registry tables in `app`.
It never holds external API keys and never touches files.

Auth: HTTP Basic, checked here for every /api/admin/* request, and for the /admin pages via Caddy
`forward_auth` -> GET /api/admin/auth. Replace with OIDC when this leaves localhost (plan §8).
"""
from __future__ import annotations

import base64
import binascii
import hmac
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
REALM = 'Basic realm="Spatial admin", charset="UTF-8"'

pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5, open=False,
                      kwargs={"row_factory": dict_row, "autocommit": True})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    pool.open(wait=True, timeout=30)
    yield
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
                  (SELECT max(r.id) FROM app.runs r WHERE r.job_id = j.id) AS run_id
           FROM app.jobs j ORDER BY j.id DESC LIMIT %s""", (min(max(limit, 1), 500),))


@app.get("/api/admin/keys", dependencies=[Depends(require_admin)])
def list_keys() -> list[dict]:
    """Which external API keys are configured for the processes that use them. Never the values."""
    return rows("SELECT key_name, configured, fingerprint, required_by, last_used_ok_at, last_error_at, reported_at "
                "FROM app.secrets_status ORDER BY key_name")
