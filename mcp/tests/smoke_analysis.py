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
CASTINE, BAR_HARBOR = "2300911265", "2300902865"  # pub.units__town unit_keys


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
        check("processes listed, a worker online", "py.town_vulnerability" in procs
              and all(p["worker_online"] for p in procs.values()), ", ".join(procs))
        d = payload(await s.call_tool("describe_process", {"process_id": "py.town_vulnerability"}))
        check("describe_process keeps the input order", list(d.get("inputs", {})) == ["unit", "place"],
              str(list(d.get("inputs", {}))))

        res = await s.call_tool("submit_job", {"process_id": "py.town_vulnerability", "inputs": {"unit": "town", "place": "nope"}})
        check("bad inputs are refused with the reason", bool(res.is_error) and "place" in text(res), text(res)[:110])

        # Python through MCP: the vulnerability assessment of Castine (a few seconds).
        j = payload(await s.call_tool("submit_job", {"process_id": "py.town_vulnerability", "inputs": {"unit": "town", "place": CASTINE}}))
        jid = j.get("job_id") if isinstance(j, dict) else None
        check("submit_job queues a Python job", isinstance(jid, int), json.dumps(j)[:100])
        r = payload(await s.call_tool("job_result", {"job_id": jid, "wait_seconds": 300}))
        rep = r.get("report") or {}
        bld = next((e for e in rep.get("exposure", []) if e.get("asset") == "Buildings"), {})
        check("job_result: succeeded, Castine's buildings counted per scenario", r.get("status") == "succeeded"
              and (rep.get("town") or {}).get("short_name") == "Castine" and bld.get("total", 0) > 0 and "fema_1pct" in bld.get("by", {}),
              f"{r.get('status')}; buildings {bld.get('total')}, scenarios {sorted(bld.get('by', {}))}")
        spec = r.get("layerSpec") or {}
        check("job_result: a LayerSpec on the published view", spec.get("source", {}).get("collection") == f"pub.analysis_sandbox__job_{jid}",
              spec.get("source", {}).get("collection", ""))

        # Cancel: queue a job and cancel it straight away.
        j = payload(await s.call_tool("submit_job", {"process_id": "py.town_vulnerability", "inputs": {"unit": "town", "place": BAR_HARBOR}}))
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
