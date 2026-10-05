# Analysis workers (plan Phase 5)

One image (`workers/Dockerfile`, `FROM spatial/geotools`, so the same GDAL/PROJ, R and Python you use with
`make r` / `make py`) runs one claim loop (`worker/`). It takes `kind = 'process'` jobs from `app.jobs` with
`FOR UPDATE SKIP LOCKED`, runs each in a child process (Python module or `Rscript`), heartbeats, honours
cancellation and timeouts, publishes the output through `app.publish_job_layer`, waits until tiPG serves it, and
stores a LayerSpec + report as the job result.

Processes live in `processes/`:

| Process | Runtime | What it computes |
|---|---|---|
| `py.agricultural_potential` | Python | Agricultural potential of a parcel (SSURGO soils, terrain) |
| `py.fire_risk` | Python | Wildfire fuel hazard of a parcel (LANDFIRE fuel models) |
| `py.town_vulnerability` | Python (PostGIS) | Community vulnerability assessment of a town (flood and sea level rise exposure) |

Add one: a Python module with `DESCRIPTOR` and `run(ctx, inputs)`, or a folder with `descriptor.json` and
`run.R` (using `rlib/ctx.R`). Descriptors follow `contracts/process.v1.schema.json`. See docs/setup/09-ml-workers.md.
