# Admin Dashboard & Dataset Registry — Plan

Status: **DRAFT — awaiting confirmation. No code written.**
Date: 2026-09-29
Related plans:
- `spatial-app-architecture.plan.md`: Phases 1–2 done. This plan **pulls forward** its Phase 3 `core-api` as the admin backend, and its Phase 5 Postgres job queue as the worker.
- `maine-projects.plan.md`: still awaiting confirmation. Its recipe extensions (§3.5) are **merged into recipe format v2 here**, so there is one format, not two.

## Verified today

| Fact | Evidence |
|---|---|
| Provenance today is **one row per `src_*` table** in `app.datasets`. It has no runs, parts, outputs, vintage, coverage or freshness | `db/migrations/20260929000300_app_datasets.sql` |
| **No backend API exists**: the frontend is a static SPA, and tiPG only exposes `pub` | `compose.yaml` services: postgis, migrator, tipg, proxy, frontend, node, e2e, geotools |
| The importer is a CLI (`scripts/geoimport.py`: inspect / import / recipe / all / list / cog) and records into `app.datasets` via `record()` | code |
| Recipes: 5 Natural Earth YAMLs. Allowed keys are enforced by `RECIPE_KEYS` | `data/recipes/` |
| **SSURGO Maine: 20 survey areas** (ME005, ME011, ME027, ME031, ME601, ME602, ME606–608, ME610–615, ME617, ME619–622), all saved **2025-08-29** (ME005 is `saversion` 22) | SDA `sacatalog` |
| `sacatalog` columns: `areasymbol, areaname, saversion, saverest, fgdcmetadata, mbrminx/y, mbrmaxx/y`. So **version, date and bbox come from one cheap query** | SDA |
| Survey-area outlines are available from SDA (`sapolygon`: 24 polygons for ME; ME005 has 2,625 vertices) | SDA |
| Maine has **no NOTCOM map units**; there are **20 water map units** (`musym = 'W'`), one per area | SDA |
| **Valu1 is NOT available via SDA** (query error). It ships only with gSSURGO/gNATSGO geodatabases | SDA |
| CONUS-wide: **3,380 survey areas** | SDA |
| Census API requires a key; 3DEP, Sentinel-2 and MEGIS facts as recorded in `maine-projects.plan.md` | earlier checks |

---

## 0. Principles

1. **YAML says what we want; the DB says what happened.**
   - Recipes (`data/recipes/*.yaml`) are the source of truth for identity, upstream, license, coverage, vintage, keys, outputs and steps.
   - The DB holds observed facts: runs, jobs, parts and their versions, footprints, output stats, health, freshness and key status.
   - The DB copy of each recipe is a **synced mirror** (with the YAML's sha256), never edited directly.
2. **One execution path.** `make import-recipe …` and the dashboard both create a `job` and a `run`, and both execute the same runner code. The CLI executes inline; the UI enqueues for the worker. History looks identical.
3. **No Docker socket anywhere.** The web tier (core-api) only reads and enqueues. A worker built from the geotools image does all the work.
4. **Secrets live only in the worker's (and CLI geotools') environment.** Never in Postgres, never in the browser, never in logs.
5. **Every run is idempotent and swap-based.** Stage, validate, swap atomically, keep one previous version.

---

## 1. Architecture

```
Browser ──▶ proxy (Caddy)
              /admin*         ─ basic_auth ─▶ frontend (static SvelteKit /admin routes)
              /api/admin/*    ─ basic_auth + injected header ─▶ core-api (FastAPI, NEW)
              /tiles/*  /projects/*  /raster/* (titiler, Phase D)   unchanged/public

core-api   role admin_api: SELECT app.*, EXECUTE app.enqueue_job()/app.cancel_job(), health reads
    │  (never touches files, never holds API keys)
    ▼
PostgreSQL  app.recipes · app.dataset_outputs · app.coverages · app.dataset_parts
            app.runs · app.jobs · app.freshness_checks · app.secrets_status   (+ src_* / pub)
    ▲  LISTEN/NOTIFY 'app_jobs' + FOR UPDATE SKIP LOCKED
worker     (NEW service, image spatial/geotools, `geoimport.py worker`)
            roles loader + etl_runner + publisher; env: API keys; volumes /work, data/*
            networks: data (PostGIS), egress (downloads), api (health-check tipg/titiler)
make … ──▶ geotools (CLI) — same runner code, same tables, inline execution
```

| Service | New in | Networks | Notes |
|---|---|---|---|
| `core-api` | Phase A | api, data | FastAPI + psycopg. Not published; reached only through the proxy. The first slice of the architecture plan's core-api |
| `worker` | Phase B | data, egress, api | `restart: unless-stopped`; the only long-running service holding API keys |
| `titiler` | Phase D | api | As in the Maine plan §3.1: named-raster Caddy route, client `url=` stripped |

**DB roles** (new, least privilege):
- `admin_api`: read `app.*` and `pub.*` (for counts), execute `app.enqueue_job`, `app.cancel_job` and `app.set_recipe_enabled_request`. It has no write access to anything else.
- `etl_runner`: write access to `app.runs`, `app.jobs`, `app.dataset_*`, `app.freshness_checks`, `app.secrets_status` and `app.coverages`. It is a member of `loader`, whose `src_*` writes already exist.
- `publisher` (NOLOGIN): owns dataset-generated `pub` objects (SSURGO matviews and views) so the worker can `CREATE OR REPLACE` and `REFRESH` them. The hand-written seeds (`db/seed`) stay owned by the migration role as today.

---

## 2. Data model (dbmate migrations)

### 2.1 What lives where

| Concern | YAML (truth) | DB |
|---|---|---|
| Identity, agency, upstream URL/API, license, attribution text | ✔ | mirror in `app.recipes` |
| Vintage *requested* (e.g. `2024`, `2025-06/2025-08`, `latest`) | ✔ | mirror; *loaded* vintage in `dataset_parts` / `dataset_outputs` |
| Coverage *requested* (named extent, FIPS list, survey areas) | ✔ | resolved geometry in `app.coverages.requested_geom` |
| Coverage *received* | – | `app.coverages.received_geom`, `received_ratio` |
| Required keys | ✔ | `app.secrets_status` (configured? last used OK?) |
| Output declarations | ✔ | `app.dataset_outputs` (observed stats, health, projects using it) |
| Freshness method + cadence | ✔ | `app.freshness_checks` (observations, verdict) |
| Enabled flag | ✔ (the UI toggle **writes the YAML** through the worker; see §5) | mirror |
| Runs, jobs, logs, parts versions | – | ✔ |

### 2.2 Tables

**Migration `…_dataset_registry.sql`** creates:

- **`app.recipes`**: one row per YAML.
  - Columns: `name PK, kind, group_name, title, description, agency, upstream jsonb, license, attribution, vintage jsonb, coverage jsonb, parts jsonb, requires_keys text[], outputs jsonb, steps jsonb, freshness jsonb, retention jsonb, concurrency_class, enabled, yaml_path, yaml_sha256, synced_at, sync_error`.
  - Synced by `geoimport.py sync`, which runs automatically at the start of every command and at worker start.
  - Rows whose YAML file disappeared are kept with `yaml_path = NULL` and shown as "orphaned".
- **`app.dataset_outputs`**: one dataset → many outputs.
  - Columns: `id, recipe_name FK, kind enum(postgis_table | pub_view | materialized_view | tipg_collection | cog | tile_url), locator` (e.g. `src_ssurgo.mupolygon`, `pub.maine_soils__hsg`, `pub.maine_soils__hsg` as a tipg collection id, `maine/dem_10m`).
  - Also: `public_url, projects text[]` (derived by scanning `projects/*/project.json` for `collection` / `cog` references), `srid, crs_label, geometry_type, row_count, raster jsonb` (width, height, bands, dtype, resolution, nodata), `bytes, checksum, loaded_vintage, loaded_run_id, footprint geometry(MultiPolygon,4326), bbox box2d`.
  - Also: `health enum(ok|warn|fail|unknown), health_detail, health_checked_at`. `UNIQUE(recipe_name, kind, locator)`.
  - **Migration of existing data:** `app.datasets` rows become `postgis_table` outputs, and `app.datasets` becomes a **compatibility view** (auto-updatable, single table, so `verify_tools.py`'s cleanup `DELETE` still works). `geoimport.record()` switches to writing outputs.
- **`app.coverages`**: `recipe_name PK FK, extent_name` (e.g. `ME`, `ME+NH+VT`, `CONUS`, `survey_areas:ME*`), `spec jsonb, requested_geom, received_geom geometry(MultiPolygon,4326), bbox box2d, received_ratio numeric, missing_geom, computed_at`.
  - Requested geometry is resolved from `src_census.states` / `counties` (a small bootstrap recipe `us_states` from Census CB 500k), from `sapolygon`, or from a bbox.
- **`app.dataset_parts`**: for datasets published in pieces (SSURGO survey areas, per-state TIGER/ACS, DEM 1° tiles, MGRS tiles).
  - Columns: `id, recipe_name FK, part_key` (`ME005`, `23`, `n45w070`, `19TCH`), `part_kind, upstream_version, upstream_date, upstream_etag, upstream_last_modified, upstream_bytes, loaded_version, loaded_date, loaded_run_id, checksum, bytes, row_count, footprint geometry(MultiPolygon,4326)`.
  - Also: `status enum(current | stale | missing | loading | failed | excluded), status_detail, checked_at`. `UNIQUE(recipe_name, part_key)`.
- **`app.freshness_checks`**: `id, recipe_name, part_key NULL, method, observed jsonb` (ETag, Last-Modified, the Census vintage list, STAC item count/latest datetime, SDA `saversion`/`saverest`), `verdict enum(current|stale|unknown|error), checked_at, run_id`. The dataset badge = latest verdict, rolled up from parts where they exist (e.g. **"18/20 survey areas current"**).
- **`app.runs`**: one execution attempt.
  - Columns: `id, job_id FK NULL, recipe_name, action enum(import | download | derive | reaggregate | freshness | healthcheck | dry_run | set_enabled), params jsonb, status enum(queued | running | succeeded | failed | cancelled)`.
  - Also: `triggered_by` (`cli:robert`, `ui:admin`, `schedule`), `host, started_at, finished_at, duration interval GENERATED, bytes_downloaded, rows_written, parts_total, parts_done, progress numeric, log_tail text` (last ~16 KB, **redacted**), `error text` (redacted), `artefacts jsonb` (staged/previous paths), `report jsonb` (dry-run estimate, validation results).
- **`app.jobs`**: scheduling intent. Retries create new runs under the same job.
  - Columns: `id, recipe_name, action, params, priority, concurrency_class enum(network | raster_heavy | db), status enum(queued | running | succeeded | failed | cancel_requested | cancelled), attempts, max_attempts, run_after, locked_by, locked_at, heartbeat_at, created_by, created_at, dedupe_key`.
  - A unique partial index on `dedupe_key WHERE status IN ('queued','running')` means double-clicking "re-download" can't queue it twice.
- **`app.secrets_status`**: `key_name PK, configured bool, fingerprint` (first 8 hex of the value's sha256, **never the value**), `last_used_ok_at, last_error_at, last_error` (redacted), `required_by text[]` (derived from recipes), `reported_at`. **Written only by the worker/CLI**, the only processes that see the values.
- **Functions** (SECURITY DEFINER, owned by `etl_runner`):
  - `app.enqueue_job(recipe, action, params, created_by)`: validates the action enum, recipe existence, and allowed param keys against `recipes.coverage.editable` / `vintage.editable`. `NOTIFY app_jobs`.
  - `app.cancel_job(id)`.

**Migration `…_ssurgo_schema.sql`** (Phase C): `CALL app.ensure_src_schema('src_ssurgo')` + `src_ssurgo_stage` (same DDL, used for per-area swaps) + table DDL (§8.3).

---

## 3. Recipe format v2 (minimal, backward compatible)

The existing NE recipes keep working unchanged. v1 keys map onto v2: `source.url` → `upstream`, and `target` → a single `postgis_table` output.

New optional keys (validated in `RECIPE_KEYS`, and by a JSON Schema in `contracts/recipe.v2.schema.json` for the UI):

```yaml
kind: vector | table | raster | multi        # multi = several outputs (e.g. SSURGO)
group: maine
title / agency / attribution                  # identity (license already exists)
vintage:   { label: "ACS 2020–2024 5-year", year: 2024, editable: true }       # or {period: 2025-06-01/2025-08-31}
coverage:  { extent: states | conus | us | county | survey_areas | bbox | custom,
             states: [ME, NH, VT],            # postal or FIPS, both accepted
             survey_areas: [ME005, ...] | "state:ME",   # resolved via SDA sacatalog
             bbox: [...], editable: [states] }          # what the UI may change
parts:     { by: state | survey_area | tile_1deg | mgrs | none }
requires_keys: [CENSUS_API_KEY]               # explicit; [] means "no key needed"
outputs:   [ { type: postgis_table, target: src_x.y },
             { type: cog, target: maine/dem_10m },
             { type: pub_view, name: pub.x__y, sql: db/seed/050_maine_soils.sql, rule: hsg_dcd },
             { type: materialized_view, name: ..., rule: ... } ]
steps:     [ { op: warp, ... }, { op: hillshade, ... } ]           # op registry (Maine plan §3.5)
depends_on: [recipe, ...]
freshness: { method: http_head | census_vintages | stac_search | sda_sacatalog | arcgis_item | none,
             every: 7d, stale_after: 400d }
retention: { keep_versions: 1 }
concurrency: network | raster_heavy | db
estimate:  { bytes_per_part: 25MB }           # dry-run fallback when upstream gives no size
rules:     { hsg_dcd: "…human-readable aggregation rule…" }        # shown in the dashboard
```

### Example 1: ACS pull for selected states (API key required)

```yaml
name: acs5_cousub_nne
title: ACS 5-year: county subdivisions, northern New England
agency: U.S. Census Bureau
kind: table
group: census
vintage: { label: "ACS 2020–2024 5-year", year: 2024, editable: true }
coverage: { extent: states, states: [ME, NH, VT], editable: [states] }
parts: { by: state }
requires_keys: [CENSUS_API_KEY]
source:
  census_api: { dataset: acs/acs5, get: [NAME, B01003_001E, B19013_001E, B19013_001M],
                for: "county subdivision:*", in: "state:{state_fips} county:*" }
outputs: [ { type: postgis_table, target: src_census.acs5_cousub } ]   # non-spatial; joined on GEOID in pub views
freshness: { method: census_vintages, every: 30d }     # compares vintage.year to the newest acs/acs5 year listed
license: Public domain (U.S. Census Bureau)
attribution: "U.S. Census Bureau, ACS 5-year estimates"
concurrency: network
```

### Example 2: statewide 3DEP DEM → COG, plus hillshade

```yaml
name: me_dem_10m
title: Elevation 1/3 arc-second (Maine)
agency: USGS 3D Elevation Program
kind: raster
group: maine
vintage: { label: "3DEP 1/3″ current", year: latest }
coverage: { extent: states, states: [ME] }
parts: { by: tile_1deg }                                   # n44w071 … n48w068
requires_keys: []
source: { url_template: "/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/{tile}/USGS_13_{tile}.tif" }
steps:
  - { op: warp, srs: EPSG:26919, resolution: 10, resampling: bilinear, cutline: { coverage: true, buffer_m: 500 } }
  - { op: cog, output: maine/dem_10m }
  - { op: hillshade, from: maine/dem_10m, multidirectional: true, output: maine/hillshade_10m }
outputs:
  - { type: cog, target: maine/dem_10m }
  - { type: cog, target: maine/hillshade_10m }
  - { type: tile_url, target: "/raster/maine/hillshade_10m/{z}/{x}/{y}.png" }
freshness: { method: http_head, every: 90d }                # ETag/Last-Modified per tile → parts
retention: { keep_versions: 1 }
concurrency: raster_heavy
license: Public domain (USGS)
attribution: "USGS 3D Elevation Program"
```

### Example 3: Sentinel-2 NDVI composite from STAC

```yaml
name: me_ndvi_2025_jja
title: NDVI growing-season composite 2025 (Maine, 20 m)
agency: ESA Copernicus (via Element 84 Earth Search)
kind: raster
group: maine
vintage: { label: "Jun–Aug 2025 median", period: 2025-06-01/2025-08-31, editable: true }
coverage: { extent: states, states: [ME] }
parts: { by: mgrs }
requires_keys: []                                           # Earth Search is public
source:
  stac: { api: https://earth-search.aws.element84.com/v1, collection: sentinel-2-l2a,
          query: { "eo:cloud_cover": { lt: 60 } }, assets: [red, nir08, scl] }
steps:
  - { op: ndvi_composite, method: median, mask_scl: [0, 1, 3, 8, 9, 10, 11], resolution: 20, srs: EPSG:26919 }
  - { op: scale_int16, factor: 10000, nodata: -32768 }
  - { op: cog, output: maine/ndvi_2025_jja_20m }
outputs: [ { type: cog, target: maine/ndvi_2025_jja_20m },
           { type: tile_url, target: "/raster/maine/ndvi_2025_jja_20m/{z}/{x}/{y}.png" } ]
freshness: { method: stac_search, every: 30d }              # item count/newest datetime in the period
concurrency: raster_heavy
license: "Copernicus Sentinel data, free and open; attribution required"
attribution: "Contains modified Copernicus Sentinel data 2025"
```

### Example 4: SSURGO for Maine (multi-part, no key)

```yaml
name: ssurgo_me
title: SSURGO soils (Maine)
agency: USDA-NRCS
kind: multi
group: soils
vintage: { label: "SSURGO FY2026 refresh", year: latest }   # parts carry the real versions
coverage: { extent: survey_areas, survey_areas: "state:ME", editable: [survey_areas, states] }
parts: { by: survey_area }                                  # 20 today: ME005 … ME622
requires_keys: []                                           # SDA and Web Soil Survey need no key
source:
  wss_area: { template: "…/wss_SSA_{areasymbol}_[{savedate}].zip" }   # exact URL format verified in Phase C
  sda: { endpoint: https://sdmdataaccess.sc.egov.usda.gov/tabular/post.rest }
steps:
  - { op: ssurgo_load_area, into: src_ssurgo_stage }        # spatial + tabular per area
  - { op: ssurgo_swap_area, from: src_ssurgo_stage, to: src_ssurgo }
  - { op: ssurgo_publish, rules: [hsg_dcd, drainage_dcd, farmland] }
  - { op: mukey_cog, optional: true, from_path: data/incoming/gSSURGO_ME.gdb, output: soils/me_mukey_10m }
outputs:
  - { type: postgis_table, target: src_ssurgo.mupolygon }
  - { type: materialized_view, name: src_ssurgo.mu_themes }                       # one row per mukey
  - { type: pub_view, name: pub.maine_soils__hsg,          rule: hsg_dcd }
  - { type: pub_view, name: pub.maine_soils__hsg_gen,      rule: hsg_dcd, generalized: true }
  - { type: pub_view, name: pub.maine_soils__drainage,     rule: drainage_dcd }
  - { type: pub_view, name: pub.maine_soils__farmland,     rule: farmland }
  - { type: cog, target: soils/me_mukey_10m, optional: true }
freshness: { method: sda_sacatalog, every: 7d }             # one SDA query: saversion/saverest for all areas
rules:
  hsg_dcd:      "Hydrologic soil group, dominant condition: muaggatt.hydgrpdcd (NRCS rule: the group covering the largest share of the map unit)."
  drainage_dcd: "Drainage class, dominant condition: muaggatt.drclassdcd."
  farmland:     "Farmland classification: mapunit.farmlndcl (map-unit attribute, no aggregation)."
concurrency: db
license: Public domain (USDA-NRCS)
attribution: "Soil Survey Staff, NRCS, USDA. Soil Survey Geographic (SSURGO) Database for Maine."
```

---

## 4. Execution model

### 4.1 Code layout

`scripts/geoimport.py` stays the CLI entry point, so every `make` target keeps working. The engine moves into a small package, `scripts/etl/`:

| Module | Does |
|---|---|
| `recipes` | Load, validate, sync to `app.recipes` |
| `runner` | Job/run lifecycle, temp dirs, logging with redaction, cancel checks, heartbeats |
| `ops/` | `vector_import` (today's `do_import`), `census_api`, `sda`, `stac`, `raster` (warp, cog, hillshade, slope, contours, ndvi_composite, scale), `ssurgo` |
| `freshness` | One function per method |
| `health` | Output checks |
| `coverage` | Resolve requested geometry, compute received geometry |
| `secrets` | Presence, fingerprint, redaction |

### 4.2 CLI and worker share one path

- `make import-recipe r=X` → `geoimport.py recipe X`. It creates a job (`created_by = cli:$USER`), claims it immediately, executes inline and prints the log live. Same tables and history as the UI. `queue=1` enqueues for the worker instead.
- `make import-all`, `make import`, `make cog` and `make seed` also write runs. Ad-hoc `make import` runs get `recipe_name = NULL` and are shown as "ad hoc" in the dashboard.
- New targets:
  - `make recipes-sync`
  - `make freshness [r=]`
  - `make health-datasets`
  - `make worker-logs`
  - `make admin-password`: writes a bcrypt hash to `.env`.

### 4.3 Worker loop

- **Wake-up:** `LISTEN app_jobs`, with a poll every 5 s as a fallback.
- **Claim:** `UPDATE app.jobs SET status='running', locked_by=…, attempts=attempts+1 WHERE id = (SELECT id FROM app.jobs WHERE status='queued' AND run_after <= now() AND <class slot free> ORDER BY priority, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`.
- **Concurrency slots** per class (`network: 3`, `db: 2`, `raster_heavy: 1`), configurable. Enforced with `pg_try_advisory_lock(class_hash, slot_n)`, so several worker containers stay safe too.
- **Heartbeat** every 15 s. A reaper requeues `running` jobs with a heartbeat more than 2 minutes old (crashed worker). The partial work is safe because of staging (§4.4).
- **Retries:** only for transient errors (network, HTTP 429/5xx, SDA timeouts), with backoff `30 s·2^n` (± jitter), capped at 1 h, `max_attempts = 4`. Validation failures, a missing key or a bad recipe **fail immediately**.
- **Cancel:** the UI sets `cancel_requested`. The runner checks it between steps and parts, and kills child processes (ogr2ogr, gdalwarp) by process group. Temp files are removed; status `cancelled`.
- **Scheduler:** the worker also enqueues `freshness` jobs per `freshness.every` (cheap, network class) and a daily `healthcheck`.

### 4.4 Idempotent, atomic swaps (keep the previous version until the new one validates)

| Output | Stage | Validate | Swap | Keep previous |
|---|---|---|---|---|
| Vector table | `src_x._stage_<t>` (today's mechanism, generalized) | Rows > 0, SRID, valid geometries, **received vs requested coverage ≥ threshold** (default 99 %) | Tables with no dependent views: rename swap in one transaction. Tables with dependent views: in-place row swap (exists today) | `src_x._prev_<t>` (retention 1) |
| COG | `data/cog/<path>.tmp-<run>.tif` | COG layout, CRS, nodata, stats in range, footprint vs coverage | Move the current file to `data/cog/.versions/<path>/<run>.tif`, then `os.replace` (atomic on one filesystem); write the sidecar | `.versions/`, `keep_versions` |
| SSURGO area | `src_ssurgo_stage.*` for one `areasymbol` | Every table non-empty, all `mukey` in `muaggatt`, `mupolygon` union ≈ `sapolygon` | **One transaction** across all tables: copy the area's current rows to `src_ssurgo_prev` → `DELETE … WHERE areasymbol = X` → `INSERT … SELECT` from stage → update `dataset_parts` → commit | `src_ssurgo_prev` (retention 1) |
| Materialized/pub views | – | – | `REFRESH MATERIALIZED VIEW CONCURRENTLY` (needs a unique index) | – |

Downloads go to `data/cache/downloads/<recipe>/<part>/<etag-or-date>/` with a `.part` suffix, resuming via HTTP Range where the server supports it. A second run with an unchanged upstream (same ETag or `saversion`) is a no-op, recorded as `succeeded (unchanged)`.

### 4.5 Dry run

The dry run resolves coverage → parts, runs the freshness method per part, and reports:
- parts that would be fetched (only changed or missing ones)
- estimated bytes (HTTP `Content-Length`; STAC asset sizes; `estimate.bytes_per_part` fallback) and rows
- required keys present or missing
- free disk vs need (with a 2× safety margin)
- the concurrency class and a duration hint

The report is stored in `runs.report` and shown before the admin confirms the real run.

### 4.6 Health checks (per output; on demand and daily)

| Output kind | Check |
|---|---|
| `postgis_table` | Exists, `row_count > 0` (exact below 1 M rows, estimate above), SRID matches |
| `pub_view` / `materialized_view` | `SELECT 1 … LIMIT 1` **as `tipg_ro`** (proves the grant too); matviews also check last refresh |
| `tipg_collection` | `GET http://tipg:8000/collections/<id>` 200, plus one tile at the footprint centroid decodes with features > 0 |
| `cog` | GDAL opens it, `LAYOUT=COG`, CRS as declared, checksum unchanged since load |
| `tile_url` | titiler tile at the centroid returns 200 `image/png` of non-trivial size; a point query returns a value |

---

## 5. API keys and secrets

**Decision: environment variables (Docker secrets later) read only by the worker and the CLI geotools container. Keys are never stored in Postgres, not even pgcrypto-encrypted.**

**Why not pgcrypto rows:**
- The master key would still have to live in some process that can also query the DB, so the trust boundary is no better than env vars.
- pgcrypto takes the key as a SQL argument, which can leak into `pg_stat_statements`, logs and error messages.
- Encrypted values would still end up in every `pg_dump` backup.

Env vars keep secrets out of the database, the backups and the web tier entirely.

**Compose:** API keys are listed **only** in the `worker` and `geotools` service blocks (`CENSUS_API_KEY`, `EARTHDATA_TOKEN`, `PC_SDK_SUBSCRIPTION_KEY`, …). `core-api`, `frontend`, `proxy` and `tipg` never receive them. In Phase 6 they come from AWS Secrets Manager into the worker task definition only.

**Status (`app.secrets_status`):**
- On startup and after each use, the worker writes `configured`, a `fingerprint` (8 hex of sha256, so an admin can see a rotation happened), `last_used_ok_at`, `last_error` and `required_by`.
- The dashboard's **Keys** page shows exactly that, plus which recipes are blocked by a missing key.

**Setting or rotating keys from the UI:** **not included** (recommended). Rotation = edit `.env` → `make restart s=worker`. A write-only endpoint would put the secret in the web tier's memory and request logs for little gain. If you want it later: core-api writes to a `tmpfs` secrets volume that only the worker reads, never echoes the value, and records an audit row.

**Fail fast:**
- The runner checks `requires_keys` before any network call: *"Recipe acs5_cousub_nne requires CENSUS_API_KEY, which is not configured. Add it to .env and run `make restart s=worker`."*
- The run is `failed` with no retry.
- Recipes needing no key say so explicitly (`requires_keys: []`, e.g. SSURGO/SDA, Earth Search, 3DEP), and the dashboard shows "No key needed".

**Redaction:**
- One logging filter replaces every configured secret value, plus patterns (`key=…`, `token=…`, `Authorization:`, `?key=` in URLs), with `•••`. It applies to `log_tail`, `error`, printed `$ command` lines and exception messages.
- Census keys are sent as request params and never logged. `CPL_CURL_VERBOSE` / `CPL_DEBUG` stay off.
- A unit test and a `make verify` check prove it: a fake key value must never appear in `app.runs`.

**Enable/disable:**
- The UI enqueues `set_enabled`. The worker (which has the repo mounted read/write) edits the YAML `enabled:` line with a comment-preserving round-trip (`ruamel.yaml`), then re-syncs.
- YAML stays the source of truth, and the change shows up in `git status` for review and commit.
- Alternative: a DB override column. Rejected, because it makes the DB and YAML disagree.

---

## 6. Admin API (core-api, FastAPI; all under `/api/admin`, role `admin_api`)

| Method | Path | Returns / does |
|---|---|---|
| GET | `/datasets?kind=&status=&coverage=&stale=&group=&q=` | Table rows: identity, loaded vintage, freshness badge (with parts rollup), coverage name, received ratio, size, last run, health summary |
| GET | `/datasets/{name}` | Full detail: identity, attribution, vintage (requested vs loaded vs upstream latest), coverage, outputs + health, rules, required keys + status |
| GET | `/datasets/{name}/coverage.geojson` | FeatureCollection: requested (outline), received (fill), missing, parts with `status` |
| GET | `/datasets/{name}/parts` | Parts table |
| GET | `/datasets/{name}/runs?limit=` | Run history |
| GET | `/runs/{id}` | Run detail + redacted log tail |
| GET | `/jobs?status=` · `/jobs/{id}` | Queue and live status (polled every 3 s) |
| POST | `/datasets/{name}/actions` | `{action: dry_run \| redownload \| derive \| reaggregate \| freshness \| healthcheck \| set_enabled, params: {states?, survey_areas?, vintage?, parts?, enabled?}}` → `202 {job_id}`. Params are validated against the recipe's `editable` lists |
| POST | `/jobs/{id}/cancel` | Sets cancel requested |
| GET | `/keys` | Secrets status only |
| GET | `/health` | core-api liveness plus DB check |

Coverage edits (e.g. add NH, add survey area NH001) are **run parameters**. To make them permanent, the same `set_*` YAML-edit mechanism as enable/disable updates `coverage` in the recipe.

---

## 7. UI (SvelteKit + MapLibre, under `/admin`)

| Route | Content |
|---|---|
| `/admin` | Datasets table with filters: kind, group, status (current/stale/unknown/failed), coverage, "stale only", search. Columns: name, agency, vintage, freshness badge (e.g. `18/20 current`), coverage + received %, outputs health (dots), size, last run (status and age) |
| `/admin/datasets/[name]` | Header (identity, license, attribution text to copy); **footprint map** (MapLibre: requested dashed outline, received fill, missing hatched red, parts coloured current = green / stale = amber / missing = red / loading = blue / water or NOTCOM = distinct pattern); vintage/freshness panel; **outputs** with health and "check now"; **aggregation rules** table; **parts** table for multi-part datasets; **run history**; **actions** (dry run → confirm → run; re-download changed parts; rebuild derived; re-aggregate; enable/disable; edit coverage) |
| `/admin/jobs` | Live queue: queued, running (progress, parts_done/total, heartbeat age, cancel), recent finished; polling every 3 s. SSE can replace polling later without changing the API shape |
| `/admin/runs/[id]` | Log tail (redacted), params, report, artefacts |
| `/admin/keys` | Key status table |

It reuses `StatusBadge`, the MapLibre setup and the basemap registry. Admin links are **not** in the public header. The `/admin` shell is static like the rest of the app; all data comes from `/api/admin/*` behind auth.

---

## 8. Access control

**Local (Phase A):**
- Caddy `basic_auth` on `/admin*` and `/api/admin/*`. `make admin-password` puts `ADMIN_USER` and a bcrypt `ADMIN_PASSWORD_HASH` in `.env`.
- Caddy adds a header only it knows (`X-Admin-Proxy: <random from .env>`) when forwarding to core-api, and core-api rejects requests without it. Defense in depth: core-api isn't published anyway.
- Against CSRF (basic auth is sent automatically by browsers), every POST requires `X-Requested-With: spatial-admin`, which cross-site forms can't set without a failing CORS preflight.

**When it leaves localhost (Phase 6):**
- TLS is mandatory.
- Replace basic auth with OIDC: ALB OIDC authentication or `oauth2-proxy` with Caddy `forward_auth`. core-api validates the identity header or JWT, and `triggered_by` records the user's email.
- `/admin` and `/api/admin` get their own CloudFront behaviour (not cached, no public origin), or a separate internal ALB.
- The worker has no ingress at all.
- Secrets come from Secrets Manager into the worker task only.
- Audit: runs and jobs already record who triggered what.

---

## 9. SSURGO / soils (first-class)

### 9.1 Source options

| Option | Contents | Maine | CONUS | Scriptable | Versioning | Use |
|---|---|---|---|---|---|---|
| **(a) gSSURGO** state FileGDB | MUPOLYGON, **10 m MUKEY raster** (EPSG:5070), **Valu1**, all SSURGO tables | ~0.5–1 GB zipped *(verify)* | ~40 GB+ *(verify)* | No (NRCS Box, manual download) | Annual snapshot per state | **Optional**, for the MUKEY raster and Valu1 only |
| **(b) SSURGO per survey area** (Web Soil Survey) | Spatial + tabular for one area | 20 areas, roughly 5–60 MB each *(verify)* | 3,380 areas | Yes (URL pattern to confirm in Phase C) | **Per area** (`saversion`) | **Default** for polygons and tables: matches per-area versioning and partial refresh |
| **(c) Soil Data Access** (REST SQL) | Any table; spatial as WKT (`sapolygon` easy, `mupolygon` heavy) | – | – | Yes, **no key** | Live | **Freshness** (`sacatalog`: version + date + bbox in one query), targeted attribute pulls. No Valu1 (verified). Documented request limits (≈100k rows / 32 MB, timeouts *(verify)*), so chunk by `areasymbol` |
| **(d) gNATSGO** | CONUS composite: SSURGO + STATSGO2 fill + raster-only areas | ~state FGDB | ~40 GB+ | No (Box) | Annual | **Only where SSURGO has gaps.** Maine appears fully covered (20 areas); confirm in Phase C with the `sapolygon` union vs the state outline |

**Recommendation:**
- Default to **(b) per-area SSURGO** for spatial and tabular data, and **(c) SDA** for freshness and small top-ups.
- Use **(a) gSSURGO** as a one-time manual download (`data/incoming/`) only when the MUKEY 10 m raster or Valu1 attributes (e.g. `rootznemc`, root zone depth) are wanted.
- Use **(d)** only if the coverage check finds gaps.
- **Fallback** if the WSS URL pattern proves unstable: gSSURGO Maine as the spatial source, with parts still versioned per area from `sacatalog`, so a new FY forces a full re-load.

### 9.2 Versioning per survey area

- **Parts** = `areasymbol` (20 for ME). `upstream_version`/`upstream_date` = SDA `sacatalog.saversion`/`saverest`. `loaded_version` comes from the area's own `sacatalog` table in the download.
- **Freshness:** one SDA query per coverage returns `(areasymbol, saversion, saverest, mbr*)` → per part `current` / `stale` / `missing`. The dataset badge rolls up, e.g. **"18/20 survey areas current"**.
- **Re-download** fetches only stale or missing areas (§4.4 per-area transactional swap). Unchanged areas aren't touched, and their checksums prove it.

### 9.3 Relational model in `src_ssurgo` (raw, keyed, per-area swappable)

| Table | Key | Notes |
|---|---|---|
| `legend` | `lkey` | One per survey area (`areasymbol`) |
| `sacatalog`, `sapolygon` | `areasymbol` | Version and date; area boundary → coverage footprint |
| `mapunit` | `mukey` | `musym`, `muname`, `mukind`, `farmlndcl` |
| `muaggatt` | `mukey` | NRCS pre-aggregated map-unit attributes |
| `mupolygon` | `mukey` (+ gid) | Map-unit polygons (~434,738 in ME) |
| `component` | `cokey` → `mukey` | `comppct_r`, `majcompflag`, `hydgrp`, `drainagecl` |
| `chorizon` | `chkey` → `cokey` | `hzdept_r`/`hzdepb_r`, `claytotal_r`, `om_r`, `ph1to1h2o_r`, `awc_r`, … |
| `coecoclass`, `corestrictions`, `comonth`/`cosoilmoist` | → `cokey` | Ecological class, restrictions, water table by month |
| `valu1` | `mukey` | Only if gSSURGO is loaded |

Every table gets a denormalized **`areasymbol`** column at load (via `mukey → legend`). That makes per-area delete/insert swaps and per-area row counts trivial. The keys are nationally unique, so areas never collide.

### 9.4 Flattened, map-ready outputs with explicit rules (shown in the dashboard)

| Rule id | Attribute | Method |
|---|---|---|
| `hsg_dcd` | Hydrologic soil group | `muaggatt.hydgrpdcd`: **dominant condition** (the group whose components sum to the largest share) |
| `hsg_domcomp` | Hydrologic soil group (alternative) | `hydgrp` of the **dominant component** (max `comppct_r`, tie → `majcompflag = 'Yes'`). Can differ from `hsg_dcd`. Offered for comparison, not mixed |
| `drainage_dcd` | Drainage class | `muaggatt.drclassdcd` (dominant condition) |
| `farmland` | Farmland classification | `mapunit.farmlndcl` (map-unit attribute; no aggregation) |
| `wt_min` | Depth to water table | `muaggatt.wtdepannmin` (min across components of the annual minimum, cm) |
| `aws_0_100` | Available water storage 0–100 cm | `muaggatt.aws0100wta` (component-% weighted) |
| `clay_0_30_wtd` | Clay % 0–30 cm | **Depth-weighted** over horizons clipped to 0–30 cm within each component, then **component-%-weighted** across components with data (normalized by the sum of their `comppct_r`) |
| `rootzone_valu1` | Root zone depth | `valu1.rootznemc` (gSSURGO only) |

**Implementation:**
- `src_ssurgo.mu_themes`: a **materialized view**, one row per `mukey`, one column per rule, unique index on `mukey` so it can refresh concurrently.
- `src_ssurgo.mupolygon_sub`: `ST_Subdivide(geom, 256)`, for fast tile clipping.
- `pub.maine_soils__<theme>`: detail layer, `minzoom 10`.
- `pub.maine_soils__<theme>_gen`: generalized layer for z6–9. Simplified 30–50 m in EPSG:26919, dissolved by class per area, slivers < 1 ha dropped. Keeps tiles under tiPG's 10,000 features.

**Raster path (optional, Phase D):**
1. gSSURGO MUKEY 10 m → COG `soils/me_mukey_10m`.
2. Thematic rasters built by a lookup join `mukey → mu_themes.<rule>` (GDAL VRT LUT or numpy take) → small int8 COGs per theme with categorical colormaps in titiler.

**Re-aggregate action:** refresh `mu_themes` and rebuild the `_gen` tables and thematic COGs from the loaded tables. **No download.** It's also the action to run after changing a rule.

**Coverage map for SSURGO:**
- Areas are coloured by part status.
- Water map units (20 in ME) and any NOTCOM units (none in ME today, verified) are drawn with distinct patterns.
- "Requested minus received" (e.g. a state area lacking SSURGO) is hatched red.
- An area whose `mupolygon` union is under 99 % of its `sapolygon` is flagged **partial**.

---

## 10. Phasing (each phase extends `make verify` and `make e2e`)

### Phase A: read-only dashboard + run history from `make`

1. Migrations:
   - the registry tables (§2.2)
   - the `app.datasets` → `dataset_outputs` migration + compat view
   - roles `admin_api`, `etl_runner`
   - `app.jobs` created, used for inline CLI jobs only in this phase
2. `scripts/etl/` extraction (no behaviour change) + `sync` + run recording in every `geoimport` command (`triggered_by cli:$USER`, redacted log tail) + output registration + footprints (vector: `ST_Union` of simplified geometries / `ST_Extent`) + `health` (postgis_table, pub_view, tipg_collection).
3. `freshness` method `http_head` (Natural Earth recipes). Other methods raise "not yet implemented", which shows as `unknown`.
4. `core-api` service (FastAPI, read-only endpoints) + Caddy `/api/admin/*` + `basic_auth` on `/admin*` and `/api/admin/*`; `make admin-password`.
5. Frontend `/admin` (table), `/admin/datasets/[name]` (footprint map, outputs + health, runs), `/admin/runs/[id]`, `/admin/jobs` (read-only).
6. Backfill: the existing Natural Earth imports appear with a synthesized `backfill` run from their `app.datasets` rows.

**Checks:**
- `/admin` and `/api/admin/datasets` return **401 without credentials** and 200 with them.
- The API lists the 5 recipes. The 4 enabled ones show outputs with health `ok`; `ne_admin1` shows "disabled".
- `make import-recipe r=ne_lakes` produces a new run visible via the API with `triggered_by = cli:…`.
- A fake secret injected into a test run's environment never appears in `app.runs`.
- e2e: log in, open a dataset, the footprint map renders, and a screenshot is reviewed.

### Phase B: job queue, worker, actions

`worker` service; claim, slots, heartbeat, reaper, retries with backoff, cancel; generalized staging + swap + retention; dry run; `redownload`, `derive`, `set_enabled` (YAML edit); freshness and health scheduler; actions + cancel in the UI; jobs page polling.

**Checks:**
- `docker compose config` shows **no `docker.sock`** mount anywhere.
- Dry run for `ne_lakes` reports bytes ≈ `Content-Length`.
- API-triggered re-download succeeds and the dependent pub view survives.
- Double-enqueue is deduplicated.
- A recipe pointing at a 503 test URL retries 4× with growing delays, then fails.
- A long `sleep` test op can be cancelled within 5 s, leaving no temp files.
- A killed worker's job is requeued by the reaper and completes.
- CLI and UI runs look identical in `/api/admin/runs`.

### Phase C: SSURGO Maine end to end + keys status + coverage editing

- `src_ssurgo` + stage schema.
- Per-area downloader + transactional swap.
- `sda_sacatalog` freshness; `sapolygon` coverage.
- Rules → `mu_themes` + pub views (HSG, drainage, farmland; detail + generalized).
- `maine-soils` project (this *is* Maine plan Phase C).
- `census_vintages` freshness + ACS recipe (needs `CENSUS_API_KEY`).
- Keys page.
- Coverage editing (add survey areas or states) with a dry run first.

**Checks:**
- 20 parts, all `current`.
- `mupolygon` ≈ 434,738 rows.
- Every `mukey` in `mupolygon` joins `muaggatt`.
- Simulating one stale area (edit `loaded_version`) → freshness shows `19/20` → refresh re-loads **only** that area (other areas' checksums unchanged).
- Coverage received ≈ requested (≥ 99 %).
- tiPG tiles for `pub.maine_soils__hsg_gen` at z7 have fewer than 10,000 features, and `__hsg` at z12 renders.
- A recipe requiring an unset key fails fast with the documented message.
- The keys page shows configured/not configured without values.

### Phase D: raster/COG outputs + titiler health

- titiler + named `/raster/*` route (Maine plan §3.1).
- DEM → hillshade/slope, NDVI composite, optional MUKEY COG + thematic COGs.
- `stac_search` freshness; raster retention (`.versions/`); a disk-usage panel with per-recipe budgets.

**Checks:**
- COG validity, CRS and nodata.
- titiler tile + point for each `tile_url` output.
- Retention keeps ≤ `keep_versions` old files.
- A client-supplied `url=` is ignored by the raster route.
- A raster job holds the single `raster_heavy` slot while network jobs still run.

**Suggested order with the Maine plan:**
1. Dashboard A
2. Maine A (towns × ACS, registered through the new registry)
3. Dashboard B
4. Dashboard C (includes Maine soils)
5. Dashboard D (includes Maine terrain and NDVI)
6. Maine E

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| **Long-running raster jobs** (DEM warp, NDVI composite: tens of minutes to hours) | One `raster_heavy` slot; per-part progress; heartbeats; resumable per part/tile (completed parts cached in `data/cache/work/`); cancel between parts; dry run shows expected size and duration |
| **Disk growth and old versions** | `retention.keep_versions` (default 1); `.versions/` and `_prev_*` pruned after the next successful validation; disk panel with per-recipe budget warnings; `make prune-versions`; free-space check in the dry run (2× need) |
| **API rate limits**: Census (key required; daily caps), SDA (documented ≈100k rows / 32 MB per request, timeouts), STAC | One request per geography per state; chunk SDA by `areasymbol`/`mukey`; backoff on 429/5xx/timeouts; cache raw responses under `data/cache/downloads/` so re-aggregation and resets don't re-hit APIs; network slot limit 3 |
| **Partial coverage** (a failed part, truncated file, API page limit) | Requested vs received geometry ratio with a validation threshold; per-part status; row-count sanity vs upstream counts (SDA `COUNT`, ACS row counts); the swap never happens on failed validation |
| **SSURGO aggregation ambiguity** | Named rules only, documented in YAML → dashboard → legend subtitle ("dominant condition"); alternative derivations as separate columns, never silently mixed; re-aggregate after rule changes |
| **Large polygon counts** (435k soils; contours) | Subdivided detail tables; generalized `_gen` layers per zoom; unique-index matviews for concurrent refresh; `TIPG_MAX_FEATURES_PER_TILE` respected; PMTiles fallback noted in the Maine plan |
| **Secrets leakage in logs** | Keys only in worker/CLI env; redaction filter on every log path; never print URLs containing keys; verify test with a canary value; `pg_dump` backups contain no secrets by construction |
| **Web Soil Survey URL instability** | Verify in Phase C; fall back to gSSURGO (manual) for spatial data, keeping SDA-based per-area freshness |
| **YAML ↔ DB drift** | Sync on every command and at worker start; `yaml_sha256` shown; "orphaned" and "sync error" states visible in the dashboard |
| **UI edits touching YAML** (enable/disable, coverage) | Comment-preserving edits; changes appear in `git status` for review; every edit logged as a run |
| **Worker privilege creep** | Separate `etl_runner` / `loader` / `publisher` roles; core-api only reads and enqueues via SECURITY DEFINER functions with validated inputs |

---

## 12. Decisions needed (recommendations first)

1. **Pull `core-api` (FastAPI) forward** as the admin backend now (recommended), rather than building admin endpoints into another service.
2. **Secrets:** worker/CLI env only, no DB storage, **no UI key entry** (recommended). The dashboard shows status only.
3. **Enable/disable and coverage edits write the YAML** via the worker (recommended; YAML stays the truth), vs a DB override column.
4. **SSURGO default source:** per-area Web Soil Survey + SDA (recommended); gSSURGO only for the MUKEY raster/Valu1; gNATSGO only for gaps.
5. **Live job status:** polling every 3 s first (recommended); SSE later.
6. **Auth:** Caddy basic_auth + proxy header + CSRF header locally (recommended); OIDC (ALB or oauth2-proxy) when deployed.
7. **Retention:** keep 1 previous version for tables, SSURGO areas and COGs (recommended).
8. **Ordering with the Maine plan:** Dashboard A before Maine A (recommended), so Maine datasets are tracked from their first run.

**Next step:** on confirmation, implement **Phase A only** and stop at its exit gate with a screenshot of `/admin`.
