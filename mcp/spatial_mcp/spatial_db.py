"""spatial-db: read-only exploration of the PostGIS database for MCP clients (plan Phase 4, §4.2).

Connects as `mcp_ro`, which can SELECT from `pub` (the published views tiPG serves) and `src_*` (raw imports),
and nothing else: no `app` registry, no writes, no DDL. Every transaction is read-only and statements time out
after 15 seconds. Free-form SQL is limited to one read statement and at most 1,000 rows.

Run: python -m spatial_mcp.spatial_db   (stdio; Claude Code starts it through .mcp.json)
"""
from __future__ import annotations

import re
import time

import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from psycopg import sql

from .common import IDENT, QUALIFIED, connect, first_line, jsonable

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
MAX_ROWS = 1000
# One read statement: SELECT / WITH / EXPLAIN / SHOW / VALUES / TABLE (after comments and whitespace).
READ_STATEMENT = re.compile(r"^\s*(?:(?:--[^\n]*\n|/\*.*?\*/)\s*)*(select|with|explain|show|values|table)\b", re.I | re.S)
CURSOR_OK = {"select", "with", "values", "table"}  # statements a server-side cursor can stream

server = MCPServer(
    name="spatial-db",
    title="Spatial database (read-only)",
    instructions=(
        "Read-only access to the project's PostGIS database. `pub` holds the published views and functions that "
        "the web maps draw (named pub.<project>__<layer>, e.g. pub.maine_overview__towns); `src_*` schemas hold raw "
        "imports (src_census, src_e911, src_nwi, src_dmr, src_bpl, src_attains, src_energy, src_climate, src_ne, ...). "
        "Most geometry is EPSG:4326. Start with list_schemas, list_tables and describe_table; use spatial_summary for "
        "extents and value distributions; use run_readonly_sql for anything else (select geometry as "
        "ST_AsGeoJSON(geom) or ST_AsText(geom); add WHERE/LIMIT for big tables such as src_nwi.wetlands or "
        "src_e911.addresses). Writes and DDL are refused: new layers go through reviewed SQL files and mapgen."
    ),
)


# ---- catalog ---------------------------------------------------------------------------------------------

_VISIBLE_SCHEMAS = r"""
SELECT n.nspname AS schema, obj_description(n.oid, 'pg_namespace') AS comment
FROM pg_namespace n
WHERE (n.nspname = 'pub' OR n.nspname LIKE 'src\_%') AND has_schema_privilege(n.oid, 'USAGE')
ORDER BY n.nspname = 'pub' DESC, n.nspname
"""

_RELATIONS = """
SELECT c.relname AS name,
       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'p' THEN 'table' WHEN 'v' THEN 'view'
                      WHEN 'm' THEN 'materialized view' WHEN 'f' THEN 'foreign table' END AS kind,
       (SELECT postgis_typmod_type(a.atttypmod) FROM pg_attribute a
         WHERE a.attrelid = c.oid AND a.atttypid = 'geometry'::regtype AND NOT a.attisdropped AND a.attnum > 0
         ORDER BY a.attnum LIMIT 1) AS geometry_type,
       (SELECT postgis_typmod_srid(a.atttypmod) FROM pg_attribute a
         WHERE a.attrelid = c.oid AND a.atttypid = 'geometry'::regtype AND NOT a.attisdropped AND a.attnum > 0
         ORDER BY a.attnum LIMIT 1) AS srid,
       CASE WHEN c.relkind IN ('r', 'p', 'm') THEN greatest(c.reltuples, 0)::bigint END AS rows_estimate,
       obj_description(c.oid, 'pg_class') AS comment
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm', 'f') AND has_table_privilege(c.oid, 'SELECT')
ORDER BY c.relname
"""

_FUNCTIONS = """
SELECT p.proname AS name, 'function' AS kind, pg_get_function_arguments(p.oid) AS arguments,
       pg_get_function_result(p.oid) AS result, obj_description(p.oid, 'pg_proc') AS comment
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = %s AND has_function_privilege(p.oid, 'EXECUTE')
ORDER BY p.proname
"""


def _schemas(conn) -> list[str]:
    return [r["schema"] for r in conn.execute(_VISIBLE_SCHEMAS).fetchall()]


def _relation(conn, name: str) -> dict:
    if not QUALIFIED.match(name):
        raise ToolError(f"name must be schema.table in lowercase, e.g. pub.maine_overview__towns (got {name!r})")
    schema, rel = name.split(".", 1)
    if schema not in _schemas(conn):
        raise ToolError(f"schema {schema!r} is not available; use list_schemas")
    row = conn.execute(
        """SELECT c.oid, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = %s AND c.relname = %s AND has_table_privilege(c.oid, 'SELECT')""", (schema, rel)).fetchone()
    if not row:
        raise ToolError(f"no table or view {name}; use list_tables({schema!r})")
    return row


@server.tool(annotations=READ_ONLY)
def list_schemas() -> list[dict]:
    """Schemas you can read: `pub` (published map layers) and the `src_*` source schemas, with table counts."""
    with connect() as conn:
        out = []
        for r in conn.execute(_VISIBLE_SCHEMAS).fetchall():
            n = conn.execute(
                """SELECT count(*) AS n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
                   WHERE s.nspname = %s AND c.relkind IN ('r','p','v','m','f')""", (r["schema"],)).fetchone()["n"]
            out.append({"schema": r["schema"], "relations": n, "comment": r["comment"]})
        return out


@server.tool(annotations=READ_ONLY)
def list_tables(schema: str) -> list[dict]:
    """Tables, views and functions in one schema: kind, geometry type, SRID, estimated rows, comment."""
    if not IDENT.match(schema):
        raise ToolError("schema must be a lowercase identifier, e.g. pub or src_census")
    with connect() as conn:
        if schema not in _schemas(conn):
            raise ToolError(f"schema {schema!r} is not available; use list_schemas")
        rels = [jsonable(dict(r)) for r in conn.execute(_RELATIONS, (schema,)).fetchall()]
        funcs = [jsonable(dict(r)) for r in conn.execute(_FUNCTIONS, (schema,)).fetchall()] if schema == "pub" else []
        return rels + funcs


@server.tool(annotations=READ_ONLY)
def describe_table(name: str) -> dict:
    """Columns, geometry (type, SRID), estimated rows, indexes and comment of `schema.table`. For a pub view, also
    its SQL definition and the source tables it reads."""
    with connect() as conn:
        rel = _relation(conn, name)
        oid = rel["oid"]
        cols = conn.execute(
            """SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type, NOT a.attnotnull AS nullable,
                      col_description(a.attrelid, a.attnum) AS comment
               FROM pg_attribute a WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""",
            (oid,)).fetchall()
        geoms = conn.execute(
            """SELECT a.attname AS column, postgis_typmod_type(a.atttypmod) AS type, postgis_typmod_srid(a.atttypmod) AS srid
               FROM pg_attribute a WHERE a.attrelid = %s AND a.atttypid = 'geometry'::regtype AND a.attnum > 0
                 AND NOT a.attisdropped ORDER BY a.attnum""", (oid,)).fetchall()
        info = conn.execute(
            """SELECT greatest(c.reltuples, 0)::bigint AS rows_estimate, obj_description(c.oid, 'pg_class') AS comment,
                      CASE WHEN c.relkind IN ('v', 'm') THEN pg_get_viewdef(c.oid, true) END AS definition
               FROM pg_class c WHERE c.oid = %s""", (oid,)).fetchone()
        indexes = conn.execute(
            """SELECT ic.relname AS name, am.amname AS method, pg_get_indexdef(i.indexrelid) AS definition
               FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_am am ON am.oid = ic.relam
               WHERE i.indrelid = %s ORDER BY ic.relname""", (oid,)).fetchall()
        out = {"name": name, "kind": {"r": "table", "p": "table", "v": "view", "m": "materialized view",
                                      "f": "foreign table"}[rel["relkind"]],
               "columns": cols, "geometry": geoms, "indexes": indexes, "comment": info["comment"]}
        if rel["relkind"] in ("r", "p", "m"):
            out["rows_estimate"] = info["rows_estimate"]
        if info["definition"]:
            out["definition"] = info["definition"]
            out["reads_from"] = [r["name"] for r in conn.execute(
                """SELECT DISTINCT d.refobjid::regclass::text AS name FROM pg_rewrite r
                   JOIN pg_depend d ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass
                                   AND d.refclassid = 'pg_class'::regclass
                   WHERE r.ev_class = %s AND d.refobjid <> %s ORDER BY 1""", (oid, oid)).fetchall()]
        return jsonable(out)


@server.tool(annotations=READ_ONLY)
def run_readonly_sql(sql_text: str, limit: int = 200) -> dict:
    """Run ONE read-only statement (SELECT, WITH, EXPLAIN, SHOW, VALUES, TABLE) and return at most `limit` rows
    (max 1000). Runs in a read-only transaction with a 15 s timeout. Select geometry as ST_AsGeoJSON(geom) or
    ST_AsText(geom); raw geometry comes back as shortened hex."""
    m = READ_STATEMENT.match(sql_text or "")
    if not m:
        raise ToolError("only one read statement is allowed: SELECT, WITH, EXPLAIN, SHOW, VALUES or TABLE")
    limit = max(1, min(int(limit), MAX_ROWS))
    started = time.monotonic()
    try:
        with connect() as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            if m.group(1).lower() in CURSOR_OK:
                with conn.cursor(name="mcp_read") as cur:  # streams; never buffers a huge result
                    cur.execute(sql_text)
                    rows = cur.fetchmany(limit + 1)
                    columns = [d.name for d in cur.description or []]
            else:
                cur = conn.execute(sql_text)
                rows = cur.fetchmany(limit + 1) if cur.description else []
                columns = [d.name for d in cur.description or []]
            conn.rollback()
    except psycopg.Error as e:
        raise ToolError(f"database error: {first_line(e)}") from None
    truncated = len(rows) > limit
    rows = rows[:limit]
    return {"columns": columns, "rows": [[jsonable(r[c]) for c in columns] for r in rows], "row_count": len(rows),
            "truncated": truncated, "elapsed_ms": round((time.monotonic() - started) * 1000)}


@server.tool(annotations=READ_ONLY)
def spatial_summary(table: str, field: str | None = None) -> dict:
    """Row count, geometry types, SRID, extent (lon/lat), empty and invalid geometries (invalid counted on the first
    10,000 rows) of `schema.table`; with `field`, its value distribution (numeric: min/max/mean/quartiles;
    otherwise: the 10 most common values)."""
    with connect() as conn:
        rel = _relation(conn, table)
        g = conn.execute(
            """SELECT a.attname AS col, postgis_typmod_srid(a.atttypmod) AS srid FROM pg_attribute a
               WHERE a.attrelid = %s AND a.atttypid = 'geometry'::regtype AND a.attnum > 0 AND NOT a.attisdropped
               ORDER BY a.attnum LIMIT 1""", (rel["oid"],)).fetchone()
        schema, name = table.split(".", 1)
        t = sql.Identifier(schema, name)
        try:
            out: dict = {"table": table}
            out["rows"] = conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(t)).fetchone()["n"]
            if g:
                gc = sql.Identifier(g["col"])
                r = conn.execute(sql.SQL(
                    """SELECT count({g}) AS with_geometry, count(*) FILTER (WHERE ST_IsEmpty({g})) AS empty,
                              ST_SRID(min({g})) AS srid, ST_Extent({g})::geometry AS ext
                       FROM {t}""").format(g=gc, t=t)).fetchone()
                bbox = None
                if r["ext"] is not None and r["srid"]:
                    b = conn.execute(
                        "SELECT ST_XMin(e) AS xmin, ST_YMin(e) AS ymin, ST_XMax(e) AS xmax, ST_YMax(e) AS ymax "
                        "FROM ST_Transform(ST_SetSRID(%s::geometry, %s), 4326) e", (r["ext"], r["srid"])).fetchone()
                    bbox = [round(b[k], 5) for k in ("xmin", "ymin", "xmax", "ymax")]
                types = conn.execute(sql.SQL(
                    "SELECT GeometryType({g}) AS type, count(*) AS n FROM {t} WHERE {g} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
                ).format(g=gc, t=t)).fetchall()
                invalid = conn.execute(sql.SQL(
                    "SELECT count(*) FILTER (WHERE NOT ST_IsValid(x)) AS n FROM (SELECT {g} AS x FROM {t} WHERE {g} IS NOT NULL LIMIT 10000) s"
                ).format(g=gc, t=t)).fetchone()["n"]
                out["geometry"] = {"column": g["col"], "declared_srid": g["srid"], "srid": r["srid"],
                                   "with_geometry": r["with_geometry"], "empty": r["empty"],
                                   "invalid_in_first_10000": invalid, "types": types, "extent_lonlat": bbox}
            if field:
                if not IDENT.match(field):
                    raise ToolError("field must be a lowercase column name")
                ftype = conn.execute(
                    """SELECT format_type(a.atttypid, a.atttypmod) AS type FROM pg_attribute a
                       WHERE a.attrelid = %s AND a.attname = %s AND NOT a.attisdropped""", (rel["oid"], field)).fetchone()
                if not ftype:
                    raise ToolError(f"{table} has no column {field!r}; use describe_table")
                f = sql.Identifier(field)
                if ftype["type"].split("(")[0] in ("integer", "bigint", "smallint", "numeric", "real", "double precision"):
                    out["field"] = conn.execute(sql.SQL(
                        """SELECT %s AS name, %s AS type, count({f}) AS non_null, count(*) - count({f}) AS nulls,
                                  min({f})::float8 AS min, max({f})::float8 AS max, avg({f})::float8 AS mean,
                                  percentile_cont(ARRAY[0.25, 0.5, 0.75]) WITHIN GROUP (ORDER BY {f})::float8[] AS quartiles
                           FROM {t}""").format(f=f, t=t), (field, ftype["type"])).fetchone()
                else:
                    top = conn.execute(sql.SQL(
                        "SELECT {f}::text AS value, count(*) AS n FROM {t} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10"
                    ).format(f=f, t=t)).fetchall()
                    out["field"] = {"name": field, "type": ftype["type"], "top_values": top}
            return jsonable(out)
        except psycopg.Error as e:
            raise ToolError(f"database error: {first_line(e)}") from None


@server.resource("schema://{name}", mime_type="text/markdown",
                 description="A schema's tables, views and functions as Markdown (pub, src_census, ...)")
def schema_doc(name: str) -> str:
    rows = list_tables(name)
    lines = [f"# Schema `{name}`", ""]
    for r in rows:
        if r["kind"] == "function":
            lines.append(f"- **{r['name']}**({r['arguments']}) → {r['result']}" + (f": {r['comment']}" if r["comment"] else ""))
        else:
            geo = f", {r['geometry_type']} SRID {r['srid']}" if r.get("geometry_type") else ""
            est = f", ~{r['rows_estimate']:,} rows" if r.get("rows_estimate") else ""
            lines.append(f"- **{r['name']}** ({r['kind']}{geo}{est})" + (f": {r['comment']}" if r["comment"] else ""))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    server.run("stdio")
