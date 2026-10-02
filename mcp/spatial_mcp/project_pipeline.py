"""project-pipeline: create and change map projects for MCP clients (plan Phase 4, §4.2).

What it can do: read the project registry, validate manifests and look up fields and value statistics (through
core-api, with its own scoped token), and write files under projects/<slug>/ for review: a view's SQL
(`propose_view`) and the manifest (`write_manifest`). It never runs SQL and has no database credential or Docker
access. Publishing is `./mapgen apply <slug>`, which `apply_project` checks and hands back for a person to run.

Run: python -m spatial_mcp.project_pipeline   (stdio; Claude Code starts it through .mcp.json)
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

API = os.environ.get("CORE_API_URL", "http://core-api:8000")
TIPG = os.environ.get("TIPG_URL", "http://tipg:8000")
PUBLIC = os.environ.get("PUBLIC_URL", "http://localhost:8080")
TOKEN = os.environ.get("MCP_PIPELINE_TOKEN", "")
PROJECTS = Path(os.environ.get("PROJECTS_DIR", "/projects"))

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
COLLECTION = re.compile(r"^pub\.[a-z0-9_]+$")
# Errors that make a manifest unusable as a file. Others (a view not created yet, ...) are expected before apply.
STRUCTURAL = {"E_SCHEMA", "E_SOURCE_TYPE", "E_SLUG_MISMATCH", "E_DUP_LAYER", "E_READY_TODO", "E_NO_LAYERS",
              "E_ZOOM_RANGE", "E_CONTROL_PARAM"}
# A proposed view's SELECT: one statement, reading src_* / pub only. A guardrail for obvious mistakes; the real
# gates are the person approving `./mapgen apply` and the E_VIEW_SOURCE database check after it.
FORBIDDEN = re.compile(r"(;|\b(insert|update|delete|truncate|drop|alter|create|grant|revoke|copy|do|call|vacuum|"
                       r"lock|set|reset|listen|notify|security\s+definer)\b|\b(app|pg_catalog|information_schema|"
                       r"public)\s*\.|\bpg_(read|ls|stat_file|terminate|cancel|sleep)\w*\s*\(|\bdblink\b|\blo_\w+\s*\()",
                       re.I)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE_FILE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    name="project-pipeline",
    title="Map project pipeline",
    instructions=(
        "Build map projects for the Downeast Geospatial web maps. Typical flow for a new layer: explore data with the "
        "spatial-db server; propose_view(slug, layer_id, select_sql) writes projects/<slug>/sql/NNN_<layer>.sql (you give "
        "only the SELECT; it must return an `id` column and one geometry column with an SRID, reading src_* or pub "
        "only); write_manifest(slug, manifest) writes projects/<slug>/project.json after validation (layers point at "
        "pub.<slug with _>__<layer with _>); apply_project(slug) checks everything and returns the `./mapgen apply` "
        "command, which a person runs because it needs Docker. Use collection_fields and layer_stats to choose styles "
        "(quantile breaks for numbers, top values for categories). Projects default to a Maine view. Nothing here runs "
        "SQL: proposals are files for review."
    ),
)


# ---- helpers -------------------------------------------------------------------------------------------------

def _call(method: str, path: str, body: Any = None, *, auth: bool = False, base: str = API) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if auth:
        if not TOKEN:
            raise ToolError("MCP_PIPELINE_TOKEN is not set (make mcp-credentials)")
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, TimeoutError) as e:
        raise ToolError(f"cannot reach {base}: {e}; is the stack up (make up)?") from None
    try:
        return status, json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return status, raw.decode(errors="replace")[:300]


def _check_slug(slug: str) -> str:
    if not SLUG.match(slug or ""):
        raise ToolError(f"invalid slug {slug!r}: lowercase letters, digits and single dashes, e.g. maine-coastal-towns")
    return slug


def _normalize(m: dict) -> str:
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"  # same as contracts/validate.normalize


def _validate(manifest: Any) -> dict:
    status, rep = _call("POST", "/api/admin/projects/validate", manifest, auth=True)
    if status != 200 or not isinstance(rep, dict):
        raise ToolError(f"validation request failed: HTTP {status} {rep}")
    return rep


def _pending_views(slug: str) -> set[str]:
    """pub views that a SQL file in projects/<slug>/sql/ will create when applied."""
    out = set()
    for f in sorted((PROJECTS / slug / "sql").glob("*.sql")):
        out |= {m.lower() for m in re.findall(r"create\s+or\s+replace\s+view\s+(pub\.[a-z0-9_]+)", f.read_text(), re.I)}
    return out


def _annotate(rep: dict, manifest: dict, slug: str) -> dict:
    """Mark E_VIEW_MISSING errors whose view has a proposed SQL file: expected until `./mapgen apply`."""
    pending = _pending_views(slug)
    layers = manifest.get("layers") or []
    for e in rep.get("errors", []):
        if e["code"] == "E_VIEW_MISSING":
            m = re.match(r"layers\[(\d+)\]", e["path"])
            i = int(m.group(1)) if m else -1
            coll = layers[i].get("source", {}).get("collection") if 0 <= i < len(layers) else None
            e["pending_apply"] = coll in pending
    rep["blocking"] = [e for e in rep.get("errors", []) if not e.get("pending_apply")]
    return rep


def _tile_for(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    lr = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)


# ---- read tools ------------------------------------------------------------------------------------------------

@server.tool(annotations=READ)
def list_projects() -> list[dict]:
    """Registered projects: slug, title, status, layer count, whether they validate, and whether a file exists."""
    status, body = _call("GET", "/api/projects")
    if status != 200:
        raise ToolError(f"project registry: HTTP {status}")
    return [{"slug": p["slug"], "title": p["title"], "status": p["status"], "layers": p["layerCount"],
             "valid": p.get("valid", True), "has_file": (PROJECTS / p["slug"] / "project.json").is_file()}
            for p in body["projects"]]


@server.tool(annotations=READ)
def get_manifest(slug: str) -> dict:
    """A project's manifest: the file in projects/<slug>/ if there is one, else the registered version."""
    _check_slug(slug)
    path = PROJECTS / slug / "project.json"
    if path.is_file():
        return {"source": f"projects/{slug}/project.json", "manifest": json.loads(path.read_text()),
                "sql_files": sorted(f.name for f in (PROJECTS / slug / "sql").glob("*.sql"))}
    status, body = _call("GET", f"/api/projects/{slug}")
    if status != 200:
        raise ToolError(f"no project {slug} (HTTP {status})")
    return {"source": "registry", "manifest": body, "sql_files": []}


@server.tool(annotations=READ)
def validate_manifest(manifest: dict) -> dict:
    """Validate a manifest object against the contract, the rules and the live database (same checks as mapgen and
    the /admin/new wizard). Returns {ok, errors, warnings, checked}; each issue has a code, a path and a message."""
    return _validate(manifest)


@server.tool(annotations=READ)
def collection_fields(collection: str) -> dict:
    """Fields of a pub view (name, type, numeric?) and its geometry type, for building a layer and its style."""
    if not COLLECTION.match(collection or ""):
        raise ToolError("collection must look like pub.<name>")
    q = urllib.parse.urlencode({"collection": collection})
    status, body = _call("GET", f"/api/admin/projects/fields?{q}", auth=True)
    if status != 200:
        raise ToolError(f"{collection}: HTTP {status} {body}")
    return body


@server.tool(annotations=READ)
def layer_stats(collection: str, field: str, classes: int = 5) -> dict:
    """Style helper: quantile breaks (numeric field, `classes` classes) or the most common values (other fields)."""
    if not COLLECTION.match(collection or "") or not re.match(r"^[a-z_][a-z0-9_]*$", field or ""):
        raise ToolError("collection must be pub.<name> and field a lowercase column name")
    q = urllib.parse.urlencode({"collection": collection, "field": field, "k": int(classes)})
    status, body = _call("GET", f"/api/admin/projects/stats?{q}", auth=True)
    if status != 200:
        raise ToolError(f"{collection}.{field}: HTTP {status} {body}")
    return body


# ---- file-writing tools -------------------------------------------------------------------------------------------

@server.tool(annotations=WRITE_FILE)
def propose_view(slug: str, layer_id: str, select_sql: str, description: str = "", overwrite: bool = False) -> dict:
    """Write projects/<slug>/sql/NNN_<layer>.sql creating pub.<slug_>__<layer_> from your SELECT, for review.

    Give only the SELECT (no semicolon). It must return an `id` column and exactly one geometry column with an SRID
    (cast if needed: geom::geometry(MultiPolygon, 4326)), and read only src_* tables or pub views. Nothing is executed
    here: `./mapgen apply <slug>` runs the file through the migrator after a person approves it."""
    _check_slug(slug)
    if not SLUG.match(layer_id or ""):
        raise ToolError("layer_id must be lowercase letters, digits and single dashes, e.g. coastal-towns")
    body = (select_sql or "").strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", body, re.I):
        raise ToolError("select_sql must be a single SELECT (or WITH ... SELECT)")
    bad = FORBIDDEN.search(body)
    if bad:
        raise ToolError(f"not allowed in a published view's SELECT: {bad.group(0).strip()!r} (one statement, reading "
                        "src_* tables or pub views only)")
    layer_ = layer_id.replace("-", "_")
    view = f"pub.{slug.replace('-', '_')}__{layer_}"
    sql_dir = PROJECTS / slug / "sql"
    existing = sorted(sql_dir.glob("*.sql")) if sql_dir.is_dir() else []
    same = [f for f in existing if re.match(rf"^\d+_{re.escape(layer_)}\.sql$", f.name)]
    if same and not overwrite:
        raise ToolError(f"projects/{slug}/sql/{same[0].name} already exists; pass overwrite=true to replace it")
    if same:
        path = same[0]
    else:
        nums = [int(m.group(1)) for f in existing if (m := re.match(r"^(\d+)_", f.name))]
        path = sql_dir / f"{(max(nums, default=0) // 10 + 1) * 10:03d}_{layer_}.sql"
    note = (description or layer_id.replace("-", " ")).replace("'", "''").replace("\n", " ")[:200]
    text = (f"-- {slug}: {note} -> {view}\n"
            f"-- Proposed by the project-pipeline MCP server; review, then run ./mapgen apply {slug}.\n"
            f"CREATE OR REPLACE VIEW {view} AS\n{body};\n\n"
            f"COMMENT ON VIEW {view} IS '{slug}: {note}';\n")
    sql_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {"file": f"projects/{slug}/sql/{path.name}", "view": view, "sql": text,
            "next": f"reference {view} in a layer (write_manifest), then apply_project('{slug}')"}


@server.tool(annotations=WRITE_FILE)
def write_manifest(slug: str, manifest: dict, overwrite: bool = False) -> dict:
    """Validate a manifest and write it to projects/<slug>/project.json (adding the slug to projects/index.json).

    Refused if the manifest itself is invalid (schema, rules). Database errors for views proposed with
    propose_view but not applied yet are expected and marked `pending_apply`. Pass overwrite=true to replace an
    existing project file."""
    _check_slug(slug)
    if manifest.get("slug") != slug:
        raise ToolError(f"manifest slug {manifest.get('slug')!r} must equal {slug!r}")
    path = PROJECTS / slug / "project.json"
    if path.exists() and not overwrite:
        raise ToolError(f"projects/{slug}/project.json already exists; pass overwrite=true to replace it")
    rep = _annotate(_validate(manifest), manifest, slug)
    structural = [e for e in rep["errors"] if e["code"] in STRUCTURAL]
    if structural:
        raise ToolError("manifest not written: " + "; ".join(f"{e['code']} {e['path']}: {e['message']}" for e in structural))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_normalize(manifest))
    index = PROJECTS / "index.json"
    slugs = json.loads(index.read_text())["projects"]
    if slug not in slugs:
        index.write_text(json.dumps({"projects": slugs + [slug]}, indent=2) + "\n")
    return {"file": f"projects/{slug}/project.json", "report": rep,
            "next": f"apply_project('{slug}')" if not rep["blocking"] else "fix the blocking errors, then write again"}


@server.tool(annotations=READ)
def apply_project(slug: str) -> dict:
    """Check that a project is ready to publish and return the command that publishes it.

    Publishing needs Docker (it runs the project's SQL through the migrator, refreshes tiPG and registers the
    project), so this server does not run it: a person runs `./mapgen apply <slug>` in the repository, which
    Claude Code shows for approval. Returns ready=false with the blocking errors if something must be fixed first."""
    _check_slug(slug)
    path = PROJECTS / slug / "project.json"
    if not path.is_file():
        raise ToolError(f"no projects/{slug}/project.json; write it with write_manifest first")
    manifest = json.loads(path.read_text())
    rep = _annotate(_validate(manifest), manifest, slug)
    sql_files = sorted(f"projects/{slug}/sql/{f.name}" for f in (PROJECTS / slug / "sql").glob("*.sql"))
    ready = not rep["blocking"]
    return {"ready": ready, "command": f"./mapgen apply {slug}" if ready else None, "sql_files": sql_files,
            "creates_views": sorted(_pending_views(slug)), "blocking": rep["blocking"], "warnings": rep["warnings"],
            "what_the_command_does": "validates the manifest and styles, runs the SQL files above as the database "
                                     "owner, restarts tiPG, validates against the database and registers the project",
            "after": f"preview_urls('{slug}')"}


@server.tool(annotations=READ)
def preview_urls(slug: str) -> dict:
    """Viewer URL for a project and, per layer, a vector-tile URL at its centre with the HTTP status tiPG returns."""
    _check_slug(slug)
    m = get_manifest(slug)["manifest"]
    lon, lat = m["view"]["center"]
    z = max(0, min(14, round(m["view"]["zoom"])))
    x, y = _tile_for(lon, lat, z)
    layers = []
    for l in m["layers"]:
        src = l.get("source", {})
        if l.get("status") == "todo" or src.get("type") not in ("tipg-vector", "tipg-geojson"):
            continue
        tile = f"/collections/{src['collection']}/tiles/WebMercatorQuad/{z}/{x}/{y}"
        try:
            with urllib.request.urlopen(TIPG + tile, timeout=30) as r:
                status, size = r.status, len(r.read())
        except urllib.error.HTTPError as e:
            status, size = e.code, 0
        except (urllib.error.URLError, TimeoutError):
            status, size = 0, 0
        layers.append({"layer": l["id"], "tile_url": f"{PUBLIC}/tiles{tile}", "status": status, "bytes": size})
    return {"viewer": f"{PUBLIC}/p/{slug}", "layers": layers}


if __name__ == "__main__":
    server.run("stdio")
