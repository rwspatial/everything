# 09 · Analysis workers: R and Python processes (Phase 5)

An **analysis process** is an R or Python program that takes a place (a parcel or a town) or a published layer, computes
something (a vulnerability assessment, a suitability score, a model) and writes a new layer. You run it from the browser (`/admin/analysis`), from Claude Code
(the `analysis` MCP server, docs/setup/08-mcp.md) or through the API. The result appears on a map without any
frontend change: it is an ordinary `tipg-vector` layer.

```
/admin/analysis or MCP ──POST /api/admin/jobs──▶ core-api ──checks inputs──▶ app.jobs (queued)
                                                                               │ FOR UPDATE SKIP LOCKED
worker (FROM geotools) ◀───────────────────────────────────────────────────────┘
  └─ child process: python -m worker.child … | Rscript run.R
       reads pub.<view> ─▶ writes ml_out.job_<id>
  └─ app.publish_job_layer(id) ─▶ pub.analysis_sandbox__job_<id> ─▶ tiPG ─▶ map
```

## Run the worker

```bash
make build-tools    # once: the worker is built FROM the geotools image
make workers-up     # build and start it (make bootstrap does this too)
make workers-logs   # follow it
docker compose --profile workers up -d --scale worker=2   # more workers: jobs are claimed safely in parallel
```

A worker registers its processes at start-up (`app.processes`). `/admin/analysis` warns when no worker has
reported in two minutes.

## The processes

| Process | Runtime | Inputs | Output fields |
|---|---|---|---|
| `py.agricultural_potential`: agricultural potential of a parcel | Python, SSURGO + titiler zonal statistics | a parcel (place analysis, run from the project workspace) | each soil unit's `score`, `class`, `limits`; method: `/admin/methods/agricultural-potential` |
| `py.fire_risk`: wildfire fuel hazard of a parcel | Python, LANDFIRE FBFM40 via titiler | a parcel (place analysis, run from the project workspace) | each fuel type's `hazard`, `class`; method: `/admin/methods/fire-risk` |
| `py.town_vulnerability`: community vulnerability assessment of a town | Python, PostGIS | a town (place analysis; batch: `make vulnerability towns="…"`) | the hazard scenarios in the town (`scenario`, `horizon`, `connection`); report: exposure tables, relative risk, social vulnerability, draft actions; method: `/admin/methods/town-vulnerability` |

All three are place analyses. The layer analysis that ran on any published layer (Getis-Ord Gi* hot spots) was removed
on 2026-10-05; /admin/analysis and the Analysis Sandbox stay for the next one (see git history for a worked example).

## In the browser: /admin/analysis

1. Pick a process. The form comes from its descriptor.
2. Choose a layer and a field, then **Run**.
3. Watch the progress. The result shows its report and a live preview.
4. Click **Add to Analysis Sandbox**. The layer is added to the `analysis-sandbox` project as a new registry version.

To keep that version in git, run `./mapgen export analysis-sandbox`.

## The API (admin login, or the analysis MCP token)

| Method | Path | |
|---|---|---|
| GET | `/api/admin/processes` | descriptors, `worker_online` |
| POST | `/api/admin/jobs` | `{"process": "py.town_vulnerability", "inputs": {"unit": "town", "place": "<unit_key>"}}`. Returns 201 with the job, 422 with `{errors: [{input, message}]}`, or 200 with `deduplicated: true` when the same job is already queued or running |
| GET | `/api/admin/jobs/{id}` | status, progress, `result` (`collection`, `layerSpec`, `report`) or `error` (`message`, `log_tail`) |
| POST | `/api/admin/jobs/{id}/cancel` | a queued job is cancelled at once; a running one within seconds |
| POST | `/api/admin/jobs/{id}/promote` | admin only: `{"project": "analysis-sandbox"}` adds the layer to that project |

Job states: `queued`, then `running`, then one of `succeeded`, `failed` or `cancelled`.
- **Heartbeat and timeout:** the worker heartbeats every 5 s. A job is killed at its descriptor's `timeoutSec`.
- **Lost workers:** if a worker stops heartbeating for 60 s, its job is requeued, up to `max_attempts` (2).
- **Success means mappable:** a job only reports `succeeded` once tiPG serves its layer. That takes up to one
  `TIPG_CATALOG_TTL`: 30 s in dev, 300 s by default.

## Add a process

Python: add `workers/processes/<name>.py` with a `DESCRIPTOR` and `run(ctx, inputs)`:

```python
DESCRIPTOR = {"id": "py.my_process", "runtime": "python", "version": "1.0.0", "title": "…",
              "inputs": {"collection": {"type": "collection-ref", "title": "Layer", "required": True},
                         "field": {"type": "field-ref", "title": "Field", "of": "collection", "dtype": "numeric"}},
              "outputs": {"layer": {"type": "vector-layer"}}, "resources": {"timeoutSec": 900}}

def run(ctx, inputs):
    gdf = ctx.read_collection(inputs["collection"], [inputs["field"]])   # GeoDataFrame with id + fields
    ctx.progress(0.5, "computing")
    gdf["score"] = ...
    rows = ctx.write_layer(gdf, {"score": "double precision"})           # ml_out.job_<id>, typed geometry, GiST
    return {"rows": rows, "style": {...}, "legend": {...}, "popup": "{score}", "report": {...}}
```

R: add `workers/processes/<name>/descriptor.json` and `run.R`, using `rlib/ctx.R`: `ctx_open()`,
`ctx_read_collection()`, `ctx_progress()`, `ctx_write_layer()` and `ctx_result()` (no R process ships at the moment;
the helpers and the R runtime in the worker image stay ready for one).

Descriptors follow `contracts/process.v1.schema.json`; the worker refuses to start with an invalid one. The
returned `style` and `legend` must pass the project manifest contract, as any hand-written layer must. Then
`make workers-up` rebuilds the worker, and the new process appears in `/admin/analysis` and the MCP server.

## Security

- **Worker role (`worker_rw`):** reads `src_*` and `pub`, writes only its own `ml_out.job_<id>` tables, and claims
  and updates jobs.
- **Publishing:** only `app.publish_job_layer(id)` publishes, and only for a running job whose table has an `id`
  and one geometry column with an SRID. It creates exactly `pub.analysis_sandbox__job_<id>`.
- **core-api (`app_rw`):** may create jobs and change only their `status`, for cancellation.
- **Worker container:** no Docker socket, a read-only filesystem except `/tmp`, all capabilities dropped,
  internal networks only.
