"""analysis: run R and Python analysis processes for MCP clients (plan Phase 4 §4.2 + Phase 5).

A thin client over core-api's jobs API with its own scoped token (MCP_ANALYSIS_TOKEN): list and describe
processes, submit jobs, follow them, read results, cancel. No database credential, no files. A finished job's
result is an ordinary layer (LayerSpec on pub.analysis_sandbox__job_<id>); a person adds it to a map in
/admin/analysis.

Run: python -m spatial_mcp.analysis   (stdio; Claude Code starts it through .mcp.json)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

API = os.environ.get("CORE_API_URL", "http://core-api:8000")
PUBLIC = os.environ.get("PUBLIC_URL", "http://localhost:8080")
TOKEN = os.environ.get("MCP_ANALYSIS_TOKEN", "")
FINAL = {"succeeded", "failed", "cancelled"}
MAX_WAIT = 600

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
SUBMIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
CANCEL = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    name="analysis",
    title="Spatial analysis jobs (R and Python)",
    instructions=(
        "Run spatial statistics on published map layers. list_processes shows what is available (e.g. "
        "py.getis_ord_hotspots: Gi* hot spots; r.local_moran: Local Moran's I clusters); describe_process gives the "
        "inputs (collection = a pub view such as pub.maine_overview__towns; field = one of its numeric columns, see "
        "the spatial-db or project-pipeline servers). submit_job returns a job id; job_result(job_id, wait_seconds) "
        "waits for it and returns the report and a ready-to-use LayerSpec. Results become layers on "
        "pub.analysis_sandbox__job_<id>; a person adds them to a map in /admin/analysis."
    ),
)


def _call(method: str, path: str, body: Any = None) -> tuple[int, Any]:
    if not TOKEN:
        raise ToolError("MCP_ANALYSIS_TOKEN is not set (make mcp-credentials)")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw.decode(errors="replace")[:300]
    except (urllib.error.URLError, TimeoutError) as e:
        raise ToolError(f"cannot reach core-api: {e}; is the stack up (make up)?") from None


def _job(job_id: int) -> dict:
    status, body = _call("GET", f"/api/admin/jobs/{int(job_id)}")
    if status != 200:
        raise ToolError(f"job {job_id}: HTTP {status} {body}")
    return body


def _summary(j: dict) -> dict:
    out = {"job_id": j["id"], "process": j["process_id"], "status": j["status"], "progress": j.get("progress"),
           "message": j.get("progress_message"), "inputs": j.get("inputs")}
    if j.get("error"):
        out["error"] = j["error"].get("message")
    return out


@server.tool(annotations=READ)
def list_processes() -> list[dict]:
    """Available analysis processes: id, title, runtime (python or r), description, input names, and whether a
    worker is online to run them."""
    status, body = _call("GET", "/api/admin/processes")
    if status != 200:
        raise ToolError(f"processes: HTTP {status} {body}")
    return [{"id": p["id"], "title": p["title"], "runtime": p["runtime"], "version": p["version"],
             "description": p["description"], "inputs": list(p["descriptor"].get("inputs", {})),
             "worker_online": p["worker_online"]} for p in body]


@server.tool(annotations=READ)
def describe_process(process_id: str) -> dict:
    """A process's full descriptor: each input's type (collection-ref, field-ref, enum, integer, number), whether it
    is required, its default, allowed values or range, and what the output layer contains."""
    status, body = _call("GET", "/api/admin/processes")
    if status != 200:
        raise ToolError(f"processes: HTTP {status} {body}")
    for p in body:
        if p["id"] == process_id:
            return p["descriptor"]
    raise ToolError(f"no process {process_id!r}; use list_processes")


@server.tool(annotations=SUBMIT)
def submit_job(process_id: str, inputs: dict) -> dict:
    """Queue a job. Inputs are checked against the process and the live database first; problems come back as an
    error listing each input. Submitting the same inputs while a job is queued or running returns that job."""
    status, body = _call("POST", "/api/admin/jobs", {"process": process_id, "inputs": inputs})
    if status == 422:
        raise ToolError("inputs rejected: " + "; ".join(f"{e['input']}: {e['message']}" for e in body["detail"]["errors"]))
    if status not in (200, 201):
        raise ToolError(f"submit failed: HTTP {status} {body}")
    out = _summary(body)
    out["deduplicated"] = bool(body.get("deduplicated"))
    out["next"] = f"job_result({body['id']}, wait_seconds=120)"
    return out


@server.tool(annotations=READ)
def job_status(job_id: int) -> dict:
    """Status (queued, running, succeeded, failed, cancelled), progress 0-1 and the current step of a job."""
    return _summary(_job(job_id))


@server.tool(annotations=READ)
def job_result(job_id: int, wait_seconds: int = 0) -> dict:
    """A job's result: the report (statistics) and the LayerSpec of its output layer. With wait_seconds (max 600),
    waits for a queued or running job to finish first. A failed job returns its error and the end of its log."""
    deadline = time.monotonic() + max(0, min(int(wait_seconds), MAX_WAIT))
    j = _job(job_id)
    while j["status"] not in FINAL and time.monotonic() < deadline:
        time.sleep(2)
        j = _job(job_id)
    out = _summary(j)
    if j["status"] == "succeeded":
        r = j["result"]
        out.update({"collection": r["collection"], "rows": r.get("rows"), "report": r.get("report"),
                    "layerSpec": r["layerSpec"],
                    "tiles": f"{PUBLIC}/tiles/collections/{r['collection']}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}",
                    "add_to_map": f"{PUBLIC}/admin/analysis (job {j['id']}: Add to Analysis Sandbox)"})
    elif j["status"] == "failed":
        out["log_tail"] = (j.get("error") or {}).get("log_tail", "")[-1500:]
    elif j["status"] not in FINAL:
        out["note"] = "still running; call job_result again with wait_seconds"
    return out


@server.tool(annotations=CANCEL)
def cancel_job(job_id: int) -> dict:
    """Cancel a queued or running job (a running job stops within a few seconds; its output is discarded)."""
    status, body = _call("POST", f"/api/admin/jobs/{int(job_id)}/cancel")
    if status != 200:
        raise ToolError(f"job {job_id}: HTTP {status} {body}")
    return body


if __name__ == "__main__":
    server.run("stdio")
