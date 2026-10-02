"""project-pipeline MCP server over stdio. Two phases around `./mapgen apply`, run by scripts/mcp_pipeline_e2e.sh:

  python tests/smoke_pipeline.py propose   explore, propose a Maine view, write the manifest, get the apply command
  python tests/smoke_pipeline.py check     after the host ran the command: valid, registered, tiles served
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SLUG = "zz-mcp-downeast-towns"
VIEW = "pub.zz_mcp_downeast_towns__towns"
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


def payload(result):
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


MANIFEST = {
    "manifestVersion": 1, "slug": SLUG, "title": "Downeast Towns (MCP smoke test)", "status": "draft",
    "description": "Washington and Hancock County towns by median household income, built through the MCP pipeline.",
    "tags": ["maine", "test"],
    "view": {"center": [-68.0, 44.75], "zoom": 7.5, "basemap": "positron"},
    "layers": [{
        "id": "towns", "title": "Median household income", "group": "Demographics",
        "source": {"type": "tipg-vector", "collection": VIEW, "properties": ["name", "county", "median_hh_income"]},
        "style": {"kind": "maplibre", "layers": [
            {"type": "fill", "paint": {"fill-color": ["step", ["to-number", ["get", "median_hh_income"]], "#f1eef6", 55000, "#74a9cf", 70000, "#045a8d"], "fill-opacity": 0.8}},
            {"type": "line", "paint": {"line-color": "#ffffff", "line-width": 0.4}}]},
        "legend": {"type": "categorical", "title": "Median household income",
                   "items": [{"label": "under $55,000", "color": "#f1eef6"}, {"label": "$55,000–70,000", "color": "#74a9cf"},
                             {"label": "$70,000 and over", "color": "#045a8d"}]},
        "interaction": {"popup": {"template": "{name}, {county}: ${median_hh_income}"}, "inspect": True}}],
}
SELECT = ("SELECT c.id, c.name, split_part(a.name, ', ', 2) AS county, a.median_hh_income::integer AS median_hh_income, c.geom "
          "FROM src_census.cousub c JOIN src_census.acs5_2024_cousub a USING (geoid) WHERE c.countyfp IN ('009', '029')")


async def main(phase: str) -> None:
    params = StdioServerParameters(command="python", args=["-m", "spatial_mcp.project_pipeline"], env=dict(os.environ))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        if phase == "propose":
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            check("tools listed", tools == sorted(["list_projects", "get_manifest", "validate_manifest", "collection_fields",
                                                    "layer_stats", "propose_view", "write_manifest", "apply_project",
                                                    "preview_urls"]), ", ".join(tools))
            projects = {p["slug"] for p in payload(await s.call_tool("list_projects", {}))}
            check("list_projects includes the Maine maps", {"maine-overview", "maine-lands"} <= projects, f"{len(projects)} projects")
            f = payload(await s.call_tool("collection_fields", {"collection": "pub.maine_overview__towns"}))
            check("collection_fields (scoped token)", isinstance(f, dict) and f.get("geometry") == "MultiPolygon", str(f)[:80])
            st = payload(await s.call_tool("layer_stats", {"collection": "pub.maine_overview__towns", "field": "median_hh_income"}))
            check("layer_stats: income quintiles", isinstance(st, dict) and st.get("breaks") == [53618.0, 62361.0, 71635.0, 86766.0],
                  str(st)[:80])

            # Guardrails on proposed SQL and paths.
            for label, args in {
                "a second statement": {"slug": SLUG, "layer_id": "towns", "select_sql": "SELECT 1 AS id; DROP VIEW pub.maine_overview__towns"},
                "a write": {"slug": SLUG, "layer_id": "towns", "select_sql": "WITH d AS (DELETE FROM src_census.cousub RETURNING *) SELECT * FROM d"},
                "the app registry": {"slug": SLUG, "layer_id": "towns", "select_sql": "SELECT * FROM app.recipes"},
                "a path outside projects/": {"slug": "../etc", "layer_id": "towns", "select_sql": "SELECT 1 AS id"},
                "not a SELECT": {"slug": SLUG, "layer_id": "towns", "select_sql": "VACUUM src_census.cousub"},
            }.items():
                res = await s.call_tool("propose_view", args)
                check(f"propose_view refuses {label}", bool(res.is_error), text(res)[:100])

            r = payload(await s.call_tool("propose_view", {"slug": SLUG, "layer_id": "towns", "select_sql": SELECT,
                                                          "description": "Washington and Hancock County towns by income"}))
            ok = isinstance(r, dict) and r.get("file") == f"projects/{SLUG}/sql/010_towns.sql" and r.get("view") == VIEW
            check("propose_view writes the SQL file for review", ok, (r.get("file") if isinstance(r, dict) else str(r))[:100])

            bad = json.loads(json.dumps(MANIFEST))
            bad["layers"][0]["source"]["type"] = "wms"
            res = await s.call_tool("write_manifest", {"slug": SLUG, "manifest": bad})
            check("write_manifest refuses an invalid manifest", bool(res.is_error) and "E_SOURCE_TYPE" in text(res), text(res)[:100])

            r = payload(await s.call_tool("write_manifest", {"slug": SLUG, "manifest": MANIFEST}))
            errs = r.get("report", {}).get("errors", []) if isinstance(r, dict) else []
            pend = [e for e in errs if e.get("pending_apply")]
            check("write_manifest writes the file; the not-yet-created view is marked pending",
                  isinstance(r, dict) and r.get("file") == f"projects/{SLUG}/project.json" and len(pend) == 1
                  and not r["report"]["blocking"], json.dumps([e["code"] for e in errs]) if errs else str(r)[:100])

            r = payload(await s.call_tool("apply_project", {"slug": SLUG}))
            ok = isinstance(r, dict) and r.get("ready") is True and r.get("command") == f"./mapgen apply {SLUG}" \
                and r.get("creates_views") == [VIEW]
            check("apply_project: ready, returns the command instead of running it", ok, str(r)[:120])
            if ok:
                print(r["command"])  # the orchestrating script runs exactly this, standing in for the person
        else:
            m = json.loads(open(f"/projects/{SLUG}/project.json").read())
            r = payload(await s.call_tool("validate_manifest", {"manifest": m}))
            check("after apply: the manifest validates against the database", isinstance(r, dict) and r.get("ok") is True,
                  json.dumps(r.get("errors") if isinstance(r, dict) else r)[:120])
            r = payload(await s.call_tool("preview_urls", {"slug": SLUG}))
            lay = (r.get("layers") or [{}])[0] if isinstance(r, dict) else {}
            check("preview_urls: viewer link and a vector tile served", isinstance(r, dict) and r.get("viewer", "").endswith(f"/p/{SLUG}")
                  and lay.get("status") == 200 and lay.get("bytes", 0) > 500, f"{lay.get('status')} {lay.get('bytes')} bytes")
            projects = {p["slug"]: p for p in payload(await s.call_tool("list_projects", {}))}
            check("the project is registered and valid", projects.get(SLUG, {}).get("valid") is True)

    if phase == "propose":
        # The token is scoped: no saving, no deleting, no datasets.
        tok = os.environ["MCP_PIPELINE_TOKEN"]
        for method, path in (("POST", "/api/admin/projects"), ("GET", "/api/admin/datasets"), ("DELETE", "/api/admin/projects/maine-lands")):
            req = urllib.request.Request(os.environ.get("CORE_API_URL", "http://core-api:8000") + path, method=method,
                                         data=b"{}" if method == "POST" else None, headers={"Authorization": f"Bearer {tok}"})
            try:
                code = urllib.request.urlopen(req, timeout=10).status
            except urllib.error.HTTPError as e:
                code = e.code
            check(f"pipeline token cannot {method} {path}", code == 401, f"HTTP {code}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "propose"))
