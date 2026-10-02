"""core-api: admin backend for the dataset dashboard (plan: .claude/plans/admin-dashboard.plan.md).

Phase A is read-only. It connects as `admin_api`, which can only SELECT the registry tables in `app`.
It never holds external API keys and never touches files.

Auth: HTTP Basic, checked here for every /api/admin/* request, and for the /admin pages via Caddy
`forward_auth` -> GET /api/admin/auth. Replace with OIDC when this leaves localhost (plan §8).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import sys
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
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
        with urllib.request.urlopen(f"{TITILER}/cog/info?url=/data/cog/{name}.tif", timeout=10) as r:
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


@app.get("/api/projects")
def list_projects(response: Response) -> dict:
    with projects_pool.connection() as conn:
        ps = conn.execute("SELECT slug, manifest::text AS manifest, version, updated_at, validation "
                          "FROM app.projects ORDER BY position, slug").fetchall()
    response.headers["Cache-Control"] = "no-cache"
    return {"projects": [_summary(p) for p in ps]}


@app.get("/api/projects/{slug}")
def get_project(slug: str) -> Response:
    """The manifest exactly as stored (json keeps key order), for the viewer and `mapgen export`."""
    with projects_pool.connection() as conn:
        p = conn.execute("SELECT manifest::text AS manifest FROM app.projects WHERE slug = %s", (slug,)).fetchone()
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


# ---- analysis processes and jobs (Phase 5) -----------------------------------------------------------------
# Workers register processes (app.processes); jobs go on app.jobs (kind 'process'). Inputs are checked here against
# the descriptor and the live database before a job is queued, so workers only see well-formed work.

NUMERIC_TYPES = ("integer", "bigint", "smallint", "numeric", "real", "double precision")
JOB_COLUMNS = """id, process_id, status, progress::float8 AS progress, progress_message, inputs, result, error,
                 attempts, created_by, created_at, started_at, finished_at"""


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
        j = conn.execute(f"SELECT {JOB_COLUMNS} FROM app.jobs WHERE id = %s AND kind = 'process'", (job_id,)).fetchone()
    if not j:
        raise HTTPException(404, f"no analysis job {job_id}")
    return j


@app.post("/api/admin/jobs/{job_id}/cancel", dependencies=[Depends(require_admin_or_analysis)])
def cancel_job(job_id: int) -> dict:
    with projects_pool.connection() as conn:
        j = conn.execute(
            """UPDATE app.jobs SET status = CASE status WHEN 'queued' THEN 'cancelled' ELSE 'cancel_requested' END
               WHERE id = %s AND kind = 'process' AND status IN ('queued', 'running') RETURNING id, status""",
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
