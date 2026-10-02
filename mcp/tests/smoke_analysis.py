"""Smoke test for the analysis MCP server over stdio: Maine town income through both runtimes."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

fails = 0
TOWNS = "pub.maine_overview__towns"


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


async def main() -> None:
    params = StdioServerParameters(command="python", args=["-m", "spatial_mcp.analysis"], env=dict(os.environ))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
        await s.initialize()
        tools = sorted(t.name for t in (await s.list_tools()).tools)
        check("tools listed", tools == ["cancel_job", "describe_process", "job_result", "job_status", "list_processes", "submit_job"],
              ", ".join(tools))
        procs = {p["id"]: p for p in payload(await s.call_tool("list_processes", {}))}
        check("both processes listed, a worker online", set(procs) >= {"py.getis_ord_hotspots", "r.local_moran"}
              and all(p["worker_online"] for p in procs.values()), ", ".join(procs))
        d = payload(await s.call_tool("describe_process", {"process_id": "r.local_moran"}))
        check("describe_process keeps the input order", list(d.get("inputs", {})) == ["collection", "field", "label", "alpha"],
              str(list(d.get("inputs", {}))))

        res = await s.call_tool("submit_job", {"process_id": "py.getis_ord_hotspots",
                                               "inputs": {"collection": "pub.maine_coast__boat_launches", "field": "nope"}})
        check("bad inputs are refused with the reason", bool(res.is_error) and "field" in text(res), text(res)[:110])

        # Python through MCP: Gi* with 6 nearest neighbours (a different setup from the queen-contiguity runs).
        j = payload(await s.call_tool("submit_job", {"process_id": "py.getis_ord_hotspots", "inputs": {
            "collection": TOWNS, "field": "median_hh_income", "label": "namelsad", "weights": "knn", "k": 6}}))
        jid = j.get("job_id") if isinstance(j, dict) else None
        check("submit_job queues a Python job", isinstance(jid, int), json.dumps(j)[:100])
        r = payload(await s.call_tool("job_result", {"job_id": jid, "wait_seconds": 300}))
        mv = (r.get("report") or {}).get("mean_value", {})
        check("job_result: succeeded, hot spots richer than cold spots", r.get("status") == "succeeded"
              and (mv.get("hot_99") or 0) > (mv.get("all") or 1e12) > (mv.get("cold_99") or 1e12),
              f"{r.get('status')}; mean income hot {mv.get('hot_99')}, all {mv.get('all')}, cold {mv.get('cold_99')}")
        spec = r.get("layerSpec") or {}
        check("job_result: a LayerSpec on the published view", spec.get("source", {}).get("collection") == f"pub.analysis_sandbox__job_{jid}",
              spec.get("source", {}).get("collection", ""))

        # Cancel: queue an R job and cancel it straight away.
        j = payload(await s.call_tool("submit_job", {"process_id": "r.local_moran", "inputs": {
            "collection": TOWNS, "field": "pop", "label": "namelsad", "alpha": 0.01}}))
        c = payload(await s.call_tool("cancel_job", {"job_id": j["job_id"]}))
        r = payload(await s.call_tool("job_result", {"job_id": j["job_id"], "wait_seconds": 60}))
        check("cancel_job stops a job", c.get("status") in ("cancelled", "cancel_requested") and r.get("status") == "cancelled",
              f"{c.get('status')} -> {r.get('status')}")

    tok = os.environ["MCP_ANALYSIS_TOKEN"]
    for method, path in (("POST", "/api/admin/jobs/1/promote"), ("GET", "/api/admin/datasets"), ("POST", "/api/admin/projects")):
        req = urllib.request.Request(os.environ.get("CORE_API_URL", "http://core-api:8000") + path, method=method,
                                     data=b"{}" if method == "POST" else None, headers={"Authorization": f"Bearer {tok}"})
        try:
            code = urllib.request.urlopen(req, timeout=10).status
        except urllib.error.HTTPError as e:
            code = e.code
        check(f"analysis token cannot {method} {path}", code == 401, f"HTTP {code}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
