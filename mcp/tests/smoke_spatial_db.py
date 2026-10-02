"""Smoke test for the spatial-db MCP server over real stdio (the transport Claude Code uses).

Run inside the spatial/mcp image: `make mcp-test`. Exits 1 if any check fails. Maine data first.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


def payload(result) -> object:
    """Structured result if present, else the JSON in the first text block."""
    sc = result.structured_content
    if sc:
        return sc["result"] if isinstance(sc, dict) and set(sc) == {"result"} else sc
    text = result.content[0].text if result.content else ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def text(result) -> str:
    return result.content[0].text if result.content else ""


async def main() -> None:
    params = StdioServerParameters(command="python", args=["-m", "spatial_mcp.spatial_db"], env=dict(os.environ))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        tools = sorted(t.name for t in (await s.list_tools()).tools)
        check("tools listed", tools == ["describe_table", "list_schemas", "list_tables", "run_readonly_sql", "spatial_summary"],
              ", ".join(tools))

        schemas = {x["schema"] for x in payload(await s.call_tool("list_schemas", {}))}
        check("schemas: pub and the Maine src_* schemas, never app", {"pub", "src_census", "src_e911", "src_nwi"} <= schemas
              and "app" not in schemas, f"{len(schemas)} schemas")

        tables = {t["name"]: t for t in payload(await s.call_tool("list_tables", {"schema": "pub"}))}
        towns = tables.get("maine_overview__towns", {})
        check("list_tables(pub) has the Maine views with geometry", towns.get("geometry_type") == "MultiPolygon"
              and towns.get("srid") == 4326 and "hydrology_sketch__rivers_by_rank" in tables,
              f"{len(tables)} objects; towns {towns.get('geometry_type')} {towns.get('srid')}")

        d = payload(await s.call_tool("describe_table", {"name": "pub.maine_overview__towns"}))
        cols = [c["name"] for c in d.get("columns", [])]
        check("describe_table: columns, geometry and the source tables of a view",
              "median_hh_income" in cols and d.get("geometry", [{}])[0].get("srid") == 4326
              and set(d.get("reads_from", [])) == {"src_census.cousub", "src_census.acs5_2024_cousub"},
              f"{len(cols)} columns, reads {d.get('reads_from')}")

        r = payload(await s.call_tool("run_readonly_sql", {"sql_text": "SELECT count(*) AS n, count(median_hh_income) AS with_income FROM pub.maine_overview__towns"}))
        check("run_readonly_sql: 529 Maine towns, 496 with income", r.get("rows") == [[529, 496]], json.dumps(r.get("rows")))

        r = payload(await s.call_tool("run_readonly_sql", {"sql_text": "SELECT id FROM src_e911.addresses", "limit": 5000}))
        check("row limit is capped at 1000 and reported", r.get("row_count") == 1000 and r.get("truncated") is True,
              f"{r.get('row_count')} rows, truncated={r.get('truncated')}")

        r = payload(await s.call_tool("spatial_summary", {"table": "pub.maine_lands__public_lands", "field": "designation"}))
        ext = r.get("geometry", {}).get("extent_lonlat") or [0, 0, 0, 0]
        top = (r.get("field", {}).get("top_values") or [{}])[0].get("value")
        check("spatial_summary: Maine public lands extent and top designation",
              -71.2 < ext[0] < ext[2] < -66.8 and 42.9 < ext[1] < ext[3] < 47.6 and top == "Public Land",
              f"extent {ext}, top {top}")

        r = payload(await s.call_tool("spatial_summary", {"table": "pub.maine_overview__towns", "field": "median_hh_income"}))
        f = r.get("field", {})
        check("spatial_summary: income distribution", f.get("non_null") == 496 and (f.get("min") or 0) > 10000,
              f"min {f.get('min')}, median {(f.get('quartiles') or [None, None])[1]}, max {f.get('max')}")

        res = await s.read_resource("schema://src_census")
        body = res.contents[0].text if res.contents else ""
        check("resource schema://src_census lists the census tables", "cousub" in body and "acs5_2024_cousub" in body)

        refused = {
            "INSERT": "INSERT INTO pub.maine_overview__towns (id) VALUES (1)",
            "DDL": "CREATE TABLE pub.x (id int)",
            "two statements": "SELECT 1; DROP VIEW pub.maine_overview__towns",
            "writable CTE": "WITH d AS (DELETE FROM src_census.cousub RETURNING 1) SELECT count(*) FROM d",
            "app registry": "SELECT * FROM app.projects",
            "read-write transaction": "SELECT set_config('transaction_read_only', 'off', true)",
        }
        for label, q in refused.items():
            res = await s.call_tool("run_readonly_sql", {"sql_text": q})
            check(f"refused: {label}", bool(res.is_error), text(res)[:110])

        t0 = time.monotonic()
        res = await s.call_tool("run_readonly_sql", {"sql_text": "SELECT pg_sleep(30)"})
        took = time.monotonic() - t0
        check("statements time out after 15 s", bool(res.is_error) and took < 20, f"{took:.1f} s: {text(res)[:60]}")

        n = payload(await s.call_tool("run_readonly_sql", {"sql_text": "SELECT count(*) FROM src_census.cousub"}))
        check("nothing was changed", n.get("rows") == [[529]], json.dumps(n.get("rows")))

    # Defence in depth: even with the server's guard bypassed and the session switched to read-write,
    # the mcp_ro role itself cannot write or create anything.
    import psycopg
    for label, q in {"role cannot INSERT": "INSERT INTO src_census.cousub (id) VALUES (-1)",
                     "role cannot CREATE in pub": "CREATE VIEW pub.mcp_probe AS SELECT 1 AS id",
                     "role cannot UPDATE a view's table": "UPDATE src_census.acs5_2024_cousub SET pop = 0"}.items():
        try:
            with psycopg.connect(os.environ["MCP_DATABASE_URL"], autocommit=True) as conn:
                conn.execute("SET default_transaction_read_only = off")
                conn.execute(q)
            check(label, False, "the statement succeeded")
        except psycopg.errors.InsufficientPrivilege as e:
            check(label, True, str(e).splitlines()[0][:90])
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
