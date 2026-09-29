# Spatial App Generator — Architecture Plan

Status: **DRAFT rev 3 — decisions confirmed; awaiting go-ahead for Phase 1**
Date: 2026-09-29
Repo state at planning time: greenfield (README + empty .gitignore)

**Rev 2 changes:** manual GDAL/ogr2ogr data ingestion (§2.7), placeholder projects (§2.8), operator setup guide that grows each phase (§3.1), and revised open decisions (§8). Phase 1–3 deliverables and exit gates are updated to match.

**Rev 3 changes:** all decisions confirmed (§8). GDAL now ships in a `geotools` image with **R and Python 3 bound to that same GDAL/PROJ** (§2.7), which later becomes the base for the ML workers. AWS moves out of Phases 1–5 into a deferred **Phase 6**, with a "migration-friendly, not migration-ready" posture applied from Phase 1 (§5).

---

## 0. Goals and Non-Goals

**Goals**
- A repeatable framework where a new map project is added by registering a **manifest + database views**, with no frontend code changes.
- Clean container and network boundaries: DB, tile/feature API, application API, frontend, and (later) ML workers.
- Stable, versioned contracts between Svelte ↔ tiPG ↔ PostGIS, so R/Python services can plug in later by producing data and registering layers, not by editing the UI.
- A local stack (Docker Compose) that is the only runtime for Phases 1–5, built so it *can* map onto AWS later (Phase 6) without redesign.

**Non-Goals (for now)**
- Multi-tenant auth or RBAC beyond a single admin role (auth seams are designed in; the implementation comes later).
- Real-time collaborative editing of features.
- Writing application source code in this planning step.

---

## 1. System Overview

```
                         ┌──────────────────────────── edge network ────────────────────────────┐
  Browser ──HTTPS──▶  [ proxy (Caddy/Traefik) ]
  (Svelte SPA +          │  /            → frontend (static)
   MapLibre GL JS)       │  /tiles/*     → tipg        (OGC API Features + Tiles, MVT)
                         │  /api/*       → core-api    (project registry, job broker)
                         │  /raster/*    → titiler     (Phase 5, COG raster tiles)
                         └──────────────────────────────────────────────────────────────────────┘
                                    │                │                 │
                         ┌──────────┴── api network ─┴─────────────────┴──┐
                         │  tipg            core-api           titiler    │
                         └──────────┬────────────┬──────────────────┬─────┘
                                    │            │                  │ (reads COGs from object store)
                         ┌──────────┴── data network (internal) ────┴─────┐
                         │  postgis  ◀── workers-py / workers-r (Phase 5) │
                         │  minio (local S3 stand-in, Phase 5)            │
                         └────────────────────────────────────────────────┘
```

### 1.1 Services

| Service | Image basis | Role | Networks | DB role |
|---|---|---|---|---|
| `proxy` | Caddy (or Traefik) | TLS, path routing, gzip, cache headers | edge, api | — |
| `frontend` | Node build → static files served by Caddy/nginx | Svelte SPA | edge | — |
| `tipg` | `ghcr.io/developmentseed/tipg` (tag pinned in Phase 1) | OGC Features + MVT tiles from the `pub` schema | api, data | `tipg_ro` (read-only, `pub` only) |
| `core-api` | Python FastAPI | Project registry CRUD, manifest validation, job broker, health | api, data | `app_rw` |
| `postgis` | `postgis/postgis` (major version pinned in Phase 1) | Storage, spatial SQL, publication views | data | owner/migrator |
| `migrator` | one-shot container (dbmate) | Applies schema + project SQL | data | owner |
| `geotools` | Built locally from `services/geotools/Dockerfile`: `rocker/geospatial` (pinned) + Python 3 venv linked to the system GDAL. Compose `profiles: [tools]` | On-demand GDAL CLI (`ogr2ogr`, `gdal_translate`, `ogrinfo`), R, and Python 3 for imports and ad hoc analysis. Never runs as a long-lived service | data | `loader` (imports), `mcp_ro`-equivalent read role for REPL sessions |
| `workers-py` | `FROM geotools` (Phase 5) | ML / raster / analysis jobs | data | `worker_rw` |
| `workers-r` | `FROM geotools` (Phase 5) | Spatial statistics jobs | data | `worker_rw` |
| `titiler` | developmentseed/titiler (Phase 5) | Raster tiles from COGs | api, data | — |
| `minio` | MinIO (Phase 5, local only) | S3-compatible COG/object storage | data | — |

**Why a `core-api` in addition to tiPG:** tiPG should stay a pure, stateless publisher of spatial data. The project registry (writes, validation), job submission for ML, and future auth don't belong in it. Keeping them separate means tiPG can be swapped (Martin, pg_featureserv) without touching registry logic.

### 1.2 Network boundaries (Compose)

- `edge`: proxy + frontend only. The only network with published host ports (80/443).
- `api`: proxy ↔ tipg / core-api / titiler.
- `data`: `internal: true`. postgis, workers, minio, plus the API services that need DB access. **postgis is never on `edge` or `api`.**
- Workers have **no** inbound ports. They only talk to postgis (the queue) and object storage.

### 1.3 Database schema boundaries (the "publication" model)

| Schema | Owner | Contents | Visible to tiPG? |
|---|---|---|---|
| `app` | migrator | Project registry: `projects`, `layers`, `manifest_versions`, `datasets` (import provenance), `processes`, `jobs` | No |
| `src_<domain>` | migrator (schema), `loader` (tables) | Raw/ingested source tables loaded by ogr2ogr (e.g. `src_hydro.flowlines`) | No |
| `ml_out` | worker_rw | Outputs written by R/Python workers | No |
| `pub` | migrator | **Views and SQL functions only**: the publication surface | **Yes** (`TIPG_DB_SCHEMAS=pub`) |

Rule: *nothing is served unless a view or function exists in `pub`.* This is the core of the "register a DB view" workflow, and it is the security boundary: `tipg_ro` has `USAGE` on `pub` and `SELECT` on its views, with views owned by a role that can read `src_*`/`ml_out` (standard view-owner privilege semantics).

Naming convention: `pub.<project_slug>__<layer_id>`, for example `pub.flood_risk__parcels`. tiPG collection ID = `pub.flood_risk__parcels`.

---

## 2. Contracts

All contracts are versioned. JSON Schema files live in `contracts/` and are the single source of truth. TypeScript types (frontend) and Pydantic models (core-api) are **generated** from them, never hand-written twice.

### 2.1 Project Manifest (`contracts/project-manifest.v1.schema.json`)

Authored as YAML in `projects/<slug>/project.yaml`, validated by core-api, stored in `app.projects` as JSONB.

```yaml
manifestVersion: 1
slug: flood-risk                # ^[a-z][a-z0-9-]{2,40}$
status: draft                   # stub | draft | ready  (controls validator strictness + Hub badge, see §2.8)
title: Flood Risk Explorer
description: Parcels intersecting FEMA flood zones.
tags: [hydrology, parcels]
thumbnail: thumbnails/flood-risk.png
view:
  center: [-77.03, 38.90]
  zoom: 10
  bounds: null                  # optional [minx,miny,maxx,maxy]; overrides center/zoom
  basemap: osm-light            # key into basemap registry (frontend config)
layers:                         # ordered bottom → top
  - $ref: layers/zones.yaml
  - $ref: layers/parcels.yaml
panels:                         # optional UI modules, by registered key
  - legend
  - feature-inspector
  - attribute-table
```

### 2.2 LayerSpec (`contracts/layer-spec.v1.schema.json`)

A discriminated union on `source.type`. Every layer type maps to exactly one **frontend adapter**. That adapter mapping is the extension seam that keeps the UI stable.

```yaml
id: parcels                     # unique within project
title: Parcels
status: ready                   # ready | todo. A 'todo' layer skips DB checks and shows greyed out with its note
todo: null                      # e.g. "Import county parcels into src_parcels.parcels, then create pub view"
group: Base data                # layer-tree grouping
visible: true
minzoom: 12
maxzoom: 22
source:
  type: tipg-vector             # tipg-vector | tipg-geojson | geojson-url | raster-xyz | raster-cog | wms
  collection: pub.flood_risk__parcels
  tms: WebMercatorQuad
  params:                       # forwarded as query params (tiPG function args / filters)
    min_area: 500
  properties: [parcel_id, zone, area_m2]   # tiPG `properties=` → keeps tiles small
style:
  kind: maplibre                # 'maplibre' = raw layer fragments; 'preset' = named style builder
  layers:                       # MapLibre layer objects minus id/source/source-layer (injected)
    - type: fill
      paint:
        fill-color: ["match", ["get", "zone"], "AE", "#d7301f", "X", "#fdbb84", "#cccccc"]
        fill-opacity: 0.6
    - type: line
      paint: { line-color: "#333", line-width: 0.5 }
legend:
  type: categorical             # categorical | gradient | single | none
  items: [{ label: "AE (100-yr)", color: "#d7301f" }, { label: "X", color: "#fdbb84" }]
interaction:
  popup: { template: "Parcel {parcel_id}: zone {zone}" }
  inspect: true
```

`preset` style example (for the programmatic styling requirement):
```yaml
style: { kind: preset, preset: choropleth, field: area_m2, classes: 5, method: quantile, ramp: viridis }
```
Presets are pure functions `(LayerSpec, stats) → MapLibre layer[]`, registered in the frontend. Stats (quantile breaks, etc.) come from core-api (`GET /api/layers/{project}/{layer}/stats?field=`), which computes them in PostGIS.

### 2.3 Svelte ↔ tiPG (read path, spatial data)

tiPG endpoints consumed (paths are verified against the pinned tiPG version in Phase 1; tiPG path shapes have changed across minor versions):

| Purpose | Request | Response |
|---|---|---|
| List collections (dev/validation only) | `GET /tiles/collections` | OGC collections JSON |
| Collection metadata, extent, fields | `GET /tiles/collections/{cid}` and `/queryables` | JSON |
| Vector tiles (MVT) | `GET /tiles/collections/{cid}/tiles/{tms}/{z}/{x}/{y}?properties=a,b&<fn params>` | `application/vnd.mapbox-vector-tile` |
| TileJSON | `GET /tiles/collections/{cid}/tiles/{tms}/tilejson.json` | TileJSON 3.0 |
| Features as GeoJSON | `GET /tiles/collections/{cid}/items?bbox=&limit=&filter=&filter-lang=cql2-text` | GeoJSON FeatureCollection |
| Single feature | `GET /tiles/collections/{cid}/items/{fid}` | GeoJSON Feature |

Frontend rules:
- The **MVT source-layer name is whatever tiPG emits** (collection-derived). The adapter injects `source-layer` from the spec; authors never type it. Confirmed during the Phase 1 spike.
- Cache busting: every tile URL carries `&v={layer.dataVersion}`. `dataVersion` is bumped by core-api when a layer's view or underlying data is refreshed.
- `tipg-geojson` is used only for small layers (feature count below a threshold, default 5k). The manifest validator warns when a GeoJSON layer's collection exceeds this.

### 2.4 tiPG ↔ PostGIS

- tiPG discovers everything in `pub` at startup and caches its catalog (`TIPG_CATALOG_TTL`). **Registering a new view requires a catalog refresh.** Options, decided in Phase 1: (a) short TTL, (b) core-api restarts or pings tiPG after migration, (c) the migrator runs before tiPG starts in Compose (`depends_on: condition: service_completed_successfully`). Plan: (c) for deploys plus (a) for dev.
- Requirements for a publishable view:
  - exactly one geometry column, SRID declared (`geometry(MultiPolygon, 4326)` or 3857). Mixed/unknown SRIDs are rejected by the validator.
  - a stable unique ID column (`id` by convention) for `items/{fid}`.
  - a GiST index on the underlying table's geometry (the validator checks `pg_indexes` via core-api).
- **Function collections** (parametrized layers): `pub.<slug>__<fn>(<named args>) RETURNS TABLE(id, geom, ...)`. Query-string args map to function args by name. Used for "same layer, user-chosen threshold" UIs. Whether tile requests pass function args the same way items requests do is **a Phase 1 spike item**.
- Env: `TIPG_DB_SCHEMAS=["pub"]`, `TIPG_MAX_FEATURES_PER_QUERY`, `TIPG_DEFAULT_MINZOOM/MAXZOOM`, connection via `DATABASE_URL` using `tipg_ro`.

### 2.5 Svelte ↔ core-api (`/api`, OpenAPI 3.1, generated client)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects` | Hub listing: slug, title, description, tags, thumbnail, updatedAt, layerCount |
| GET | `/api/projects/{slug}` | Fully resolved manifest (`$ref`s inlined, `dataVersion` per layer) |
| POST | `/api/projects` | Create from manifest (Phase 3 creator); returns validation report |
| POST | `/api/projects/{slug}/validate` | Dry-run validation: schema + DB checks (view exists in `pub`, SRID, index, id column) |
| PUT | `/api/projects/{slug}` | Update manifest (new `manifest_versions` row) |
| GET | `/api/layers/{project}/{layer}/stats?field=&method=&classes=` | Class breaks, min/max, distinct values for preset styles |
| GET | `/api/sources/pub` | Publishable views/functions not yet bound to a layer (creator picker) |
| POST | `/api/jobs` · GET `/api/jobs/{id}` · GET `/api/processes` | Phase 5 job broker (see Phase 5) |
| GET | `/api/health` | Liveness + DB + tiPG reachability |

Error envelope (all endpoints): `{ "error": { "code": "VIEW_NOT_FOUND", "message": "...", "details": {...} } }`.

### 2.6 End-to-end data flows

**Flow A: open a project**
```
Hub ──GET /api/projects──▶ core-api ──SELECT app.projects──▶ PostGIS
User clicks card
Viewer ──GET /api/projects/flood-risk──▶ core-api (resolved manifest + dataVersions)
Viewer: for each LayerSpec → adapter[source.type].toMapLibre(spec) → {sources, layers}
MapLibre ──GET /tiles/collections/pub.flood_risk__parcels/tiles/WebMercatorQuad/{z}/{x}/{y}?properties=…&v=7──▶ proxy (cache) ──▶ tipg
tipg ──ST_AsMVT(ST_AsMVTGeom(...)) on pub view──▶ PostGIS ──▶ MVT bytes
```

**Flow B: register a new project (Phase 3)**
```
Author writes projects/<slug>/sql/*.sql (CREATE VIEW pub.<slug>__x …) + project.yaml
`mapgen apply <slug>` → migrator applies SQL → core-api POST /api/projects (validate + store)
                      → tiPG catalog refresh → project appears in Hub
```

**Flow C: ML result becomes a layer (Phase 5)**
```
UI/MCP ──POST /api/jobs {process:"py.getis_ord_hotspot", inputs:{collection:"pub.x__y", field:"rate"}}──▶ core-api
core-api INSERT app.jobs (status=queued)
worker (SELECT … FOR UPDATE SKIP LOCKED) → runs → writes ml_out.job_<id> → app.publish_job_layer() creates pub.<slug>__job_<id>
worker UPDATE app.jobs SET status=succeeded, result={layerSpec: {...}}
core-api (on poll/SSE) → returns LayerSpec → frontend adds it through the existing tipg-vector adapter. No UI changes.
```

**Flow D: manual data import (operator, Phase 1+)**
```
Operator drops file in data/incoming/  (gitignored)
make import f=rivers.gpkg t=src_hydro.rivers        (or: make import-recipe r=hydro_rivers)
  → docker compose run --rm geotools ogr2ogr … PG:"service=loader" /data/rivers.gpkg
  → post-import SQL: ANALYZE, row count, SRID check, INSERT/UPSERT app.datasets
Operator writes projects/<slug>/sql/NNN_rivers.sql (CREATE OR REPLACE VIEW pub.<slug>__rivers …)
mapgen apply <slug>  (Phase 3)  → layer goes live
```

### 2.7 Data ingestion (manual, GDAL/ogr2ogr)

Scope: an **operator** (you) loads datasets by hand. App users do not upload data, so there is no upload UI or ingestion API. That can be added later as a core-api endpoint wrapping the same script.

**Tooling: one `geotools` image containing GDAL + R + Python 3, all on the same GDAL/PROJ build.**

- **Base:** `rocker/geospatial` (pinned tag). It's Ubuntu-based and already has system GDAL/GEOS/PROJ plus R with `sf`, `terra`, `stars`, `DBI`, `RPostgres`, `spdep`, and `gstat` compiled against them.
- **Python 3 layer:** a venv at `/opt/venv` with `GDAL==$(gdal-config --version)` (the `osgeo` bindings), `pyogrio`, `shapely`, `pyproj`, `geopandas`, `rasterio`, `psycopg`, and `sqlalchemy`. The GDAL-linking packages (`pyogrio`, `rasterio`, `fiona` if used) are installed with `--no-binary` so they **link the system GDAL instead of bundling their own copies**. Otherwise R, Python, and the CLI would silently disagree on drivers and PROJ grids. The Python dependencies are locked with `requirements.lock` (pip-tools or uv).
- **Why one image rather than three:** a single GDAL/PROJ version means an ogr2ogr import, an `sf::st_read`, and a `geopandas.read_postgis` all see identical CRS transforms and driver support. Phase 5's `workers-r` and `workers-py` use `FROM geotools`, so the worker runtime is the environment you already used by hand.
- **Operation:** it sits under Compose `profiles: [tools]`, so `docker compose up` never starts it. It runs one-off (`docker compose run --rm geotools …`) on the `data` network, with `./data/incoming` mounted read-only at `/data` and `./notebooks` or `./analysis` mounted read-write for scripts.
- **Interactive use:** `make r` / `make py` open an R or Python REPL inside it, already connected to PostGIS through `pg_service.conf`. RStudio Server and Jupyter are *not* in scope now. They can be added later as an optional profile on the same image.
- **Trade-off:** the image is large (several GB) and the first build takes a while, so `make build-tools` is a documented, separate step. Rebuilds are rare because the base is pinned.
- **Host tools:** a host-installed QGIS, R, or Python still works against `127.0.0.1:5432` in the dev profile. The guide covers it as optional and doesn't require it.

**DB role `loader`:** `CREATE` + ownership on `src_*` schemas, `INSERT/UPDATE` on `app.datasets`, and nothing on `pub`/`app` otherwise. Credentials come from `.env` via libpq env vars/`pg_service.conf` mounted in the container, so passwords never appear on the command line or in shell history.

**Standard ogr2ogr invocation** (wrapped by `scripts/import.sh`, exposed as `make import`):
```
ogr2ogr -f PostgreSQL PG:"service=loader" /data/<file> [<source layer>]
  -nln <schema>.<table>
  -t_srs EPSG:4326                  # override via s=<EPSG>, or keep native with s=native
  -nlt PROMOTE_TO_MULTI
  -lco GEOMETRY_NAME=geom -lco FID=id -lco SPATIAL_INDEX=GIST -lco PRECISION=NO
  -lco LAUNDER=YES                  # lower-case, SQL-safe column names
  --config PG_USE_COPY YES          # fast bulk load
  -overwrite                        # default; append mode via m=append
  -progress
```
Script conventions and safety:
- Refuses targets outside `src_*` schemas.
- `make inspect f=<file>` runs `ogrinfo -so -al` first to show layers, CRS, feature count, and fields before anything is loaded.
- Post-import it runs `ANALYZE`, verifies the geometry SRID/type, checks for invalid geometries (count of `NOT ST_IsValid`; fixing is opt-in with `fix=1` → `ST_MakeValid`), and upserts provenance into `app.datasets`: table, source filename, file checksum, source CRS, target CRS, row count, geometry type, imported_at, license, notes.
- Supported formats cover whatever GDAL reads. The guide documents recipes for: GeoPackage, Shapefile (zipped via `/vsizip/`), GeoJSON, File Geodatabase (`OpenFileGDB`), CSV with lon/lat (`-oo X_POSSIBLE_NAMES=lon* -oo Y_POSSIBLE_NAMES=lat*`), KML/KMZ, and remote files (`/vsicurl/`, later `/vsis3/`).

**Import recipes make reinstalls repeatable.** Each dataset worth keeping gets a small recipe file, `data/recipes/<name>.yaml` (committed), with fields for source path/URL, source layer, target table, SRS, mode, license, and notes. `make import-recipe r=<name>` runs one, and `make import-all` replays all of them. After a full DB reset, `make reset-db && make import-all && make seed` rebuilds the database without re-deriving any commands. The raw files stay in `data/incoming/` (gitignored), or a recipe can point at a downloadable URL.

**Rasters:** by default, don't store rasters in PostGIS. `make cog f=<tif>` runs `gdal_translate -of COG` into `data/cog/` for TiTiler (Phase 5). `raster2pgsql` is documented only as an escape hatch for in-DB raster analysis.

**Large-data notes (manual, rare):** use `-gt 65536` for batch size, and for very large files, load into an unlogged staging table and then run `INSERT … SELECT`. Documented, not automated.

### 2.8 Placeholder projects

Three deliberately incomplete projects ship with the repo. They exercise the Hub, the Viewer, and the "incomplete" states, and they serve as templates for real projects. All use Natural Earth data (loaded by recipes, so they double as the ingestion smoke test).

| Slug | Status | What it demonstrates | Deliberately missing |
|---|---|---|---|
| `world-overview` | `draft` | `tipg-vector` countries with a choropleth preset, populated places as circles, popups | Thumbnail, description text, 1 `todo` layer ("admin-1 boundaries") |
| `hydrology-sketch` | `stub` | Rivers + lakes (`tipg-vector` / small `tipg-geojson`), a **function collection** layer (rivers filtered by `min_scalerank`) | 2 `todo` layers ("watersheds", "gauges") with import notes. No styling beyond defaults |
| `analysis-sandbox` | `stub` | Empty layer list, a `raster-xyz` placeholder, and a "Phase 5: job outputs will appear here" panel | Everything, by design. It becomes the ML output landing project |

Behavior by status:
- **Hub**: cards show a status badge and an incompleteness hint ("2 of 4 layers pending"), acting as the "creation prompts" on the splash screen. Clicking a hint shows the `todo` notes.
- **Validator**: `ready` projects get strict checks. `draft`/`stub` projects turn DB-check failures on `todo` layers into warnings, so incomplete projects still load.
- **Viewer**: `todo` layers appear greyed out in the layer tree with their note, and are never requested from tiPG.
- **Generator**: in Phase 2 they are hand-authored static JSON. In Phase 3 they are regenerated with `mapgen new --template {vector-basic|hydro|analysis}`, which proves the generator creates exactly what was hand-built.

---

## 3. Repository Layout (target)

```
/
├─ compose.yaml                 # base stack
├─ compose.dev.yaml             # bind mounts, hot reload, exposed db port
├─ compose.ml.yaml              # Phase 5 overlay: workers, titiler, minio
├─ Makefile                     # single operator control surface (§3.1)
├─ .env.example
├─ contracts/                   # JSON Schemas (source of truth) + OpenAPI
├─ data/
│  ├─ incoming/                 # raw files to import (gitignored)
│  ├─ cog/                      # generated COGs (gitignored)
│  ├─ backups/                  # pg_dump output (gitignored)
│  └─ recipes/*.yaml            # committed import recipes (§2.7)
├─ db/
│  ├─ migrations/               # app/, roles, schemas, extensions
│  └─ seed/                     # seed SQL that runs after recipes (pub views for placeholders)
├─ docs/
│  ├─ setup/                    # operator guide, grows each phase (§3.1)
│  └─ decisions/                # ADRs incl. Phase 1 spike results
├─ scripts/                     # import.sh, backup.sh, reset.sh (LF line endings enforced)
├─ projects/
│  ├─ world-overview/           # placeholder (§2.8)
│  ├─ hydrology-sketch/         # placeholder
│  ├─ analysis-sandbox/         # placeholder
│  └─ <slug>/{project.yaml, layers/*.yaml, sql/*.sql, thumbnails/}
├─ services/
│  ├─ core-api/                 # FastAPI
│  ├─ tipg/                     # config/env only (upstream image)
│  ├─ workers-py/               # Phase 5
│  └─ workers-r/                # Phase 5
├─ frontend/                    # SvelteKit (adapter-static) + MapLibre
├─ mcp/                         # Phase 4 MCP servers
├─ tools/mapgen/                # CLI: new / validate / apply
├─ services/geotools/           # Dockerfile (rocker/geospatial + Python venv), requirements.lock
├─ analysis/                    # ad hoc R/Python scripts run in geotools (mounted rw)
├─ infra/aws/                   # Phase 6 only: Terraform (not created before then)
└─ .claude/plans/
```

### 3.1 Operator setup guide (living document)

`docs/setup/` is a **deliverable of every phase**, not a one-time write-up. Each phase appends its sections, and every exit gate includes "a clean-clone walkthrough of the guide succeeds on this machine (WSL2)". Every command in the guide is a `make` target, so the guide and the tooling can't drift apart. The Makefile is the source of truth, and `make help` prints the same list.

| File | Written in | Contents |
|---|---|---|
| `01-install.md` | Phase 1 | Prerequisites: WSL2 + Docker (Docker Desktop with WSL integration **or** Docker Engine inside WSL; the guide covers both), git, make. Keep the repo on the Linux filesystem (`/home/...`, not `/mnt/c`) for bind-mount speed. Memory settings in `.wslconfig`. Clone → `cp .env.example .env` → `make up` → `make verify` |
| `02-containers.md` | Phase 1 | Container control, see table below. Includes reading health status and logs, plus what each service does |
| `03-reinstall-reset.md` | Phase 1 | Tiered reset ladder, see below. Backup/restore before any destructive step |
| `04-data-import.md` | Phase 1 | Inspect → import → verify → publish view. Per-format recipes (§2.7), writing a recipe file, CRS guidance, fixing invalid geometries, re-importing and updating an existing table, deleting a dataset |
| `05-frontend.md` | Phase 2 | Dev server vs built frontend, adding a basemap, hot reload |
| `06-projects.md` | Phase 3 | `mapgen new/validate/apply`, promoting stub → draft → ready, completing a placeholder project |
| `07-mcp.md` | Phase 4 | Registering MCP servers with Claude Code, credentials, testing |
| `08-ml-workers.md` | Phase 5 | Enabling the ML overlay, adding an R/Python process, job debugging |
| `99-troubleshooting.md` | All | Port 5432 already in use (host Postgres), CRLF line endings breaking scripts, WSL clock drift, disk space from images/volumes, tiPG not seeing a new view |

**Container control targets (Phase 1)**

| Target | Does |
|---|---|
| `make up` / `make down` | Start the stack (detached) / stop and remove containers, **keeping** data volumes |
| `make stop` / `make start` | Pause and resume containers without removing them |
| `make restart s=tipg` | Restart one service (all if `s` omitted). Use `s=tipg` after publishing new views |
| `make ps` / `make health` | Status / health of each service |
| `make logs s=tipg` | Follow logs for one service or all |
| `make psql` | psql shell as the owner role (`make psql r=loader` for another role) |
| `make shell s=<svc>` | Shell inside a running container |
| `make rebuild s=<svc>` | Rebuild the image and recreate the container |
| `make migrate` / `make seed` | Apply schema migrations / placeholder `pub` views and registry rows |
| `make inspect f=…` / `make import f=… t=…` / `make import-recipe r=…` / `make import-all` / `make datasets` | Data ingestion (§2.7). `datasets` lists `app.datasets` |
| `make build-tools` / `make r` / `make py` / `make tools-sh` | Build the geotools image / R REPL / Python REPL / bash, all DB-connected |
| `make backup` / `make restore b=<file>` | `pg_dump -Fc` to `data/backups/` (timestamped) / `pg_restore` |
| `make verify` | Automated Phase exit checks (smoke tests) |

**Reset ladder** (`03-reinstall-reset.md`). Each step is more destructive than the last. Steps 3 and 4 prompt for confirmation and offer `make backup` first.
1. **Restart**: `make restart`. Fixes stale tiPG catalog and hung services. No data loss.
2. **Recreate containers**: `make down && make up`. Picks up `.env`/compose changes. No data loss.
3. **Reset database**: `make reset-db`. Removes the postgis volume, then runs `migrate` → `import-all` → `seed`. Imported data is rebuilt from recipes. Anything imported without a recipe is **lost** (the guide says so in bold).
4. **Full reinstall**: `make nuke`. Removes containers, volumes, project images, and generated files (`data/cog`, frontend build). Then follow `01-install.md` from `make up`. Raw files in `data/incoming/` and backups are kept.

---

## 4. Phases

Each phase ends with an **exit gate**: acceptance criteria that must pass before the next phase starts. Every exit gate also includes: *setup guide sections for this phase are written, and a walkthrough from a clean clone succeeds.*

### Phase 1: Docker / PostGIS / tiPG foundation

**Deliverables**
1. `compose.yaml` with `proxy`, `postgis`, `migrator`, `tipg`, and the three networks (§1.2). Pinned image tags. Healthchecks on all services.
2. DB bootstrap migrations: extensions (`postgis`; `postgis_raster` off by default), schemas (`app`, `pub`, `src_ne`, `src_hydro`, `ml_out`), roles (`tipg_ro`, `app_rw`, `loader`, `worker_rw`) with least-privilege grants and default privileges, and the `app.datasets` provenance table.
3. **Data ingestion (§2.7)**: `geotools` image (GDAL + R + Python 3), `scripts/import.sh`, recipe format, and Natural Earth recipes (countries, populated places, rivers, lakes) that load into `src_ne`. The seed is loaded *through* the import path, not a separate SQL dump, so ingestion is exercised from day one.
4. Seed SQL: `pub` views for the three placeholder projects (§2.8), including one **function collection** for the parametrized-layer spike.
5. tiPG configured for `pub` only. Proxy routes `/tiles/*`.
6. `Makefile` with the Phase 1 targets (§3.1), `.env.example`, `.gitattributes` enforcing LF on scripts. Secrets are never committed.
7. Setup guide `01`–`04` + `99` (§3.1).

**Spike questions (answered and recorded in `docs/decisions/`)**
- Exact tiPG endpoint paths and MVT `source-layer` naming for the pinned version.
- Function-collection args on the tile endpoint.
- Catalog refresh strategy after new views are created.
- Tile performance baseline: p95 latency at z10/z14 for the seed set.

**Exit gate**
- `docker compose up` on a clean machine yields healthy services.
- `curl /tiles/collections` lists only `pub.*` collections.
- The MVT for a known tile decodes to non-empty features. GeoJSON `items` with a `bbox` returns the expected count.
- `tipg_ro` cannot `SELECT` from `src_ne` or `app` directly (negative test). `loader` cannot write outside `src_*`.
- postgis port is not reachable from the host in the non-dev profile.
- `make import` loads a GeoPackage, a zipped Shapefile, and a lon/lat CSV. Each appears in `make datasets` with correct CRS and row count.
- In `geotools`: `gdalinfo --version`, R `sf::sf_extSoftVersion()["GDAL"]`, and Python `osgeo.gdal.__version__` / `pyogrio.__gdal_version_string__` all report the **same** GDAL version. R (`sf::st_read` via `RPostgres`) and Python (`geopandas.read_postgis`) both read an imported table.
- `make backup` → `make reset-db` → the DB is rebuilt from recipes, and `make restore` of the backup also works.
- `make nuke` followed by the install guide returns to a healthy stack.

### Phase 2: Svelte / MapLibre UI shell

**Deliverables**
1. SvelteKit (Svelte 5, `adapter-static`, TypeScript), served via proxy.
2. Routes: `/` (Hub), `/p/[slug]` (Viewer), `/new` (Creator placeholder).
3. **Viewer layout** (standardized): top bar (project title, share), left panel (layer tree with toggles, opacity, groups, legend), map canvas, right drawer (feature inspector / attribute table), and a bottom status bar (coords, zoom, loading indicator).
4. **Layer adapter registry**: `adapters: Record<SourceType, LayerAdapter>` with `LayerAdapter = { toMapLibre(spec, ctx): {sources, layers}; legend?(spec); onClick?(feature, spec) }`. Initial adapters: `tipg-vector`, `tipg-geojson`, `geojson-url`, `raster-xyz`.
5. Map state store: layer visibility/order/opacity, derived from the manifest and reflected in the URL (`?layers=a,b&z=&c=`) so views are shareable.
6. For this phase only, manifests are loaded from static JSON under `frontend/static/projects/` so UI work doesn't block on core-api. Phase 3 swaps the loader behind the same `ProjectRepository` interface.
7. Basemap registry (open vector basemap + a raster fallback), keyed by name.
8. The three placeholder projects (§2.8) as hand-authored manifests. Hub status badges and incompleteness hints. `todo` layers greyed out in the layer tree.
9. Setup guide `05-frontend.md`.

**Exit gate**
- The Hub lists the 3 placeholder projects with correct badges. `world-overview` renders tiPG tiles, and `hydrology-sketch` renders a GeoJSON layer and the function-collection layer.
- `analysis-sandbox` (empty) opens without errors.
- Toggling, reordering, and opacity changes work. The legend reflects the style. Clicking a feature shows its attributes.
- Adding a third demo project requires **zero** `.svelte`/`.ts` changes (only JSON plus a `pub` view).
- Lighthouse a11y ≥ 90 on Hub. Keyboard access to the layer tree.

### Phase 3: Project Creator abstraction

**Deliverables**
1. JSON Schemas for Manifest and LayerSpec (`contracts/`), with codegen for TS types and Pydantic models, and a CI check that the generated code is up to date.
2. `core-api` service: endpoints in §2.5 (except jobs), `app.projects` / `app.layers` / `app.manifest_versions` tables, and the validation pipeline:
   - schema validation
   - DB checks: view/function exists in `pub`, single geometry column with declared SRID, `id` column, GiST index on the source, row-count warning for GeoJSON layers
   - style checks: MapLibre style-spec validation of generated layers (`@maplibre/maplibre-gl-style-spec` run in CI/CLI; core-api validates structure only)
3. `mapgen` CLI (`tools/mapgen`):
   - `mapgen new <slug>` scaffolds `projects/<slug>/` with a template manifest and a sample view SQL
   - `mapgen validate <slug>` runs offline schema + style validation, and DB checks if a DB is reachable
   - `mapgen apply <slug>` applies SQL through the migrator, then registers/updates via core-api, then triggers tiPG refresh
4. Style presets: `single`, `categorical`, `choropleth` (quantile/equal/jenks via `/stats`), `graduated-circle`, `heatmap`.
5. The frontend swaps the static loader for the core-api `ProjectRepository`. `/new` becomes a wizard: pick `pub` source → choose preset → preview live → save manifest. The wizard emits the **same YAML/JSON** the CLI consumes, so there is one path, not two.
6. `mapgen` templates (`blank`, `vector-basic`, `hydro`, `analysis`). The placeholder projects are regenerated from them and the diff against the Phase 2 hand-built versions is empty. Status-aware validation (§2.8).
7. `mapgen` also exposes the import path: `mapgen import` is a thin alias over `scripts/import.sh`, so project and data work share one CLI. Setup guide `06-projects.md`, including "complete a placeholder: import → view → flip layer to ready".

**Exit gate**
- `mapgen new demo-x && <write one SQL view> && mapgen apply demo-x` puts a working project in the Hub with no restarts beyond the documented refresh.
- Invalid manifests (bad SRID, missing view, unknown source type) fail with specific error codes.
- Round-trip: a manifest saved in the wizard and then re-exported via CLI is byte-identical after normalization.

### Phase 4: MCP architecture

#### 4.1 Evaluation: one server or several?

| Criterion | Single "spatial" MCP | Split servers |
|---|---|---|
| Blast radius / credentials | One credential set spanning read + DDL + jobs | Each server holds only the DB role it needs |
| Tool-selection quality | Large tool list, higher mis-selection risk | Small focused tool sets. Clients enable only what a task needs |
| Operational cost | One process | 3 processes, but shared library code |
| Deployment independence | Coupled releases | Analysis server can evolve with ML workers independently |

**Recommendation: split into 3 servers, sharing one internal Python package (`mcp/common`) for DB pooling, contract models, and auth.** Don't split further (e.g. one server per preset) because the operational overhead isn't worth it.

#### 4.2 Servers

**`spatial-db-mcp`** (read-only; role `mcp_ro`: `SELECT` on `pub`, `src_*`; no DDL)
- `list_schemas`, `list_tables(schema)`, `describe_table(name)` (columns, geometry type, SRID, row estimate, indexes)
- `run_readonly_sql(sql, limit≤1000)`: runs in a `READ ONLY` transaction with `statement_timeout`, and results are truncated
- `spatial_summary(table, field?)`: extent, geometry types, null counts, and value distribution
- Resources: `schema://pub`, `schema://src_*` (schema docs)

**`project-pipeline-mcp`** (the "Tile Pipeline" server; calls core-api, no direct DDL)
- `list_projects`, `get_manifest(slug)`, `validate_manifest(yaml)`
- `propose_view(slug, layer_id, sql)` writes `projects/<slug>/sql/NNN_<layer>.sql` **as a file for review**. It does not execute DDL directly (see safety note).
- `apply_project(slug)` wraps `mapgen apply` and requires explicit confirmation from the client
- `preview_tile_url(collection, z, x, y)` and `layer_stats(collection, field)`
- Safety: DDL goes through reviewed SQL files + the migrator, never through free-form MCP execution. That keeps migrations auditable and reproducible.

**`analysis-mcp`** (Phase 5 dependent; talks only to core-api `/api/jobs`, no direct DB)
- `list_processes`, `describe_process(id)`, `submit_job(process, inputs)`, `job_status(id)`, `job_result(id)` (returns a LayerSpec)
- This is a thin client over the job contract (Phase 5), so R and Python processes appear automatically.

**Transports:** stdio for local Claude Code use. Streamable HTTP behind the proxy (`/mcp/<server>`) with a bearer token for deployed/shared use. Registered in project `.mcp.json` for local dev.

**Exit gate**
- From Claude Code, an agent can go from "describe the tables" to "propose a view" to "validate manifest" to "apply" for a new project, with the apply step gated on confirmation.
- `spatial-db-mcp` rejects `INSERT/UPDATE/DDL` (tested) and enforces its timeout.
- Each server runs with a distinct credential. Credentials are not shared.

### Phase 5: R / Python ML API specifications

(Specification in this phase. Implementing a first reference process of each language is the exit gate.)

#### 5.1 Principles
- **Workers never talk to the frontend.** They consume jobs and produce (a) tables/views in PostGIS and/or (b) COGs in object storage, plus a LayerSpec. The frontend already knows how to render those through its existing adapters. **This is how R and Python plug in without frontend refactoring.**
- The job API is shaped after **OGC API – Processes** (process list, process description, async job execution, job status, and results) so it's standards-aligned and tool-friendly.
- **Language-agnostic contract**: the queue is Postgres (`app.jobs`, `FOR UPDATE SKIP LOCKED`). No Redis or Celery is required initially. A worker in any language is a loop: claim → run → write → report.

#### 5.2 Process descriptor (`contracts/process.v1.schema.json`)
```yaml
id: py.getis_ord_hotspot       # <runtime>.<name>
runtime: python                # python | r
version: 1.0.0
title: Hot spot analysis (Getis-Ord Gi*)
inputs:
  collection: { type: collection-ref, geometry: [Polygon, MultiPolygon, Point] }
  field:      { type: field-ref, of: collection, dtype: numeric }
  weights:    { type: enum, values: [queen, knn], default: queen }
  k:          { type: integer, default: 8, when: { weights: knn } }
outputs:
  layer:  { type: vector-layer, geometry: same-as-input, fields: [gi_z, gi_p, cluster] }
  report: { type: json }
defaultStyle: { kind: preset, preset: categorical, field: cluster }
resources: { cpu: 1, memoryMb: 2048, gpu: false, timeoutSec: 900 }
```
Workers self-register descriptors in `app.processes` at startup. `GET /api/processes` lists them, and the Creator/MCP render input forms from the schema.

#### 5.3 Job lifecycle (`app.jobs`)
`queued → running → succeeded | failed | cancelled`, with columns `id, process_id, inputs jsonb, status, progress, worker_id, heartbeat_at, result jsonb, error jsonb, created_by, created_at, finished_at`. A reaper requeues jobs whose `heartbeat_at` is stale. Clients get progress by polling `GET /api/jobs/{id}`, with SSE `GET /api/jobs/{id}/events` as an enhancement.

#### 5.4 Output conventions
- Vector: `ml_out.job_<uuid>` table (with GiST index), plus a `pub.<slug>__job_<shortid>` view. `result.layerSpec` uses `tipg-vector`.
- Raster: COG written to `s3://<bucket>/jobs/<uuid>/<name>.tif`. `result.layerSpec` uses `raster-cog`, served by **TiTiler** (tiPG does not serve rasters). The `raster-cog` adapter is added to the frontend once, in this phase.
- Tabular/metrics: `result.report` JSON, rendered by a generic "report" panel.
- Promotion: an ephemeral job layer can be "promoted" into a project manifest via core-api (`POST /api/projects/{slug}/layers:fromJob`).

#### 5.5 Runtime specifics
- **Python**: `workers-py` is `FROM geotools` and adds pysal/scikit-learn plus the claim loop. A GPU variant (CUDA base) is a separate image and can't share the geotools base, so it's documented as an exception if it's ever needed.
- **R**: `workers-r` is `FROM geotools` and adds a small R claim loop (via `DBI`/`RPostgres`). A plumber sidecar only if synchronous calls are ever required.
- Because both inherit from `geotools`, a script prototyped with `make r` / `make py` in Phases 1–4 becomes a process with no environment changes.
- Both use the same `worker_rw` role: `SELECT` on `src_*`/`pub`, full rights on `ml_out`, `UPDATE` on `app.jobs`, and `CREATE VIEW` in `pub` only via a `SECURITY DEFINER` function `app.publish_job_layer(job_id, slug)`, so workers can't create arbitrary objects in `pub`.

**Exit gate**
- One Python process (hot spot) and one R process (e.g. kriging → COG, or spdep Moran's I) run end-to-end: submitted from the UI and from `analysis-mcp`, then rendered as layers with no frontend changes beyond the one-time `raster-cog` adapter.

---

## 5. AWS: Phase 6 (deferred) and migration posture

**AWS is not part of Phases 1–5.** Everything runs locally under Docker Compose. Nothing in `infra/aws/` is created, and no AWS account is needed.

### 5.1 Migration-friendly posture (applied from Phase 1)

The goal is *generally prepared, not 100% ready*: cheap habits now so Phase 6 is configuration work, not a redesign. Each item costs little or nothing locally.

| Habit (Phases 1–5) | Why it eases migration later |
|---|---|
| All config via environment variables / `.env`, and no hostnames baked into code (services use `DATABASE_URL`, `TIPG_*`, `PUBLIC_BASE_URL`) | ECS task definitions and Secrets Manager inject the same variables |
| Stateless containers. The only state is the postgis volume (and MinIO in Phase 5) | Maps onto Fargate tasks + RDS + S3 |
| Per-service DB roles from day one | They become separate Secrets Manager entries without a code change |
| Pin the PostGIS major/minor version to one that **RDS for PostgreSQL offers** (checked at Phase 1 pin time) | Avoids extension or version surprises on RDS |
| No superuser-only extensions or `postgresql.conf` hacks. Roles are created by migrations, not by the image's init scripts | RDS has no superuser, and migrations run unchanged there |
| Object storage only through S3 APIs (MinIO locally, Phase 5) | Switching to S3 is an endpoint/credentials change |
| Frontend is a static build that takes its API base URLs from runtime config (`/config.json`) | S3 + CloudFront hosting works as-is |
| Import recipes + `pg_dump -Fc` backups | Seeding RDS means restoring a dump or replaying recipes through a tunnel |

Deliberately **not** done before Phase 6: Terraform code, CI/CD to AWS, IAM design, TLS/domain setup, autoscaling, and CloudFront cache policies.

### 5.2 Phase 6 target (reference only; confirmed decisions: Terraform, RDS for PostgreSQL)

| Local | AWS |
|---|---|
| proxy | CloudFront (static + tile caching) → ALB (path routing `/tiles`, `/api`, `/raster`, `/mcp`) |
| frontend | S3 bucket (static build) behind CloudFront (OAC) |
| tipg, core-api, titiler | ECS on **Fargate** services, private subnets, autoscaling on CPU/request count |
| postgis | **RDS for PostgreSQL** with PostGIS (confirmed) |
| geotools (manual imports) | Run locally against RDS through an SSM port-forward or bastion, where only the `PG:` connection changes. Alternatively a one-off ECS task |
| migrator | ECS one-off task run by CI before service deploy |
| workers | ECS Fargate services scaled on queue depth (custom CloudWatch metric from `app.jobs`). GPU jobs go to **AWS Batch** or ECS on EC2 GPU capacity (Fargate has no GPU) |
| minio | S3 |
| secrets | Secrets Manager (DB creds per role), injected into task definitions |
| networking | VPC: public subnets (ALB only), private app subnets (ECS), isolated DB subnets (RDS). Security groups mirror Compose networks: only the ECS SGs → RDS SG:5432 |
| observability | CloudWatch Logs + Container Insights. OpenTelemetry from core-api/workers |
| IaC | **Terraform** (confirmed) in `infra/aws/`, written in Phase 6 |

**Why not EKS initially:** at this service count (≤ 6 services), ECS/Fargate has far lower operational overhead. Revisit EKS if the ML worker fleet grows into heterogeneous GPU scheduling or if the team already runs Kubernetes.

**Tile caching:** CloudFront caches `/tiles/*` keyed on path + query string (the `v=` data version makes cache invalidation unnecessary). TTL is long (1 day or more) because version bumps change the URL.

---

## 6. Cross-Cutting Concerns

- **Security**: least-privilege DB roles per service. The `pub` schema is the only publication surface. `run_readonly_sql` is sandboxed. CORS is locked to the frontend origin. No DB port is exposed outside dev. Auth seam: the proxy/ALB can add OIDC (Cognito) later, and core-api reads identity from a header, so no service redesign is needed.
- **Testing**: contract tests (JSON Schema fixtures) shared by TS and Python. Integration tests against Compose (Phase 1 exit checks automated as a `make verify` / pytest suite). Playwright E2E for Hub → Viewer → toggle → inspect.
- **CI**: lint, codegen drift check, schema validation of all `projects/*`, Compose-based integration tests, and image builds.
- **Performance**: `properties=` pruning, minzoom per layer, `ST_Simplify`/`ST_SnapToGrid` in heavy views or dedicated `__lowzoom` views, and materialized views for expensive joins (refreshed by `mapgen`/jobs, bumping `dataVersion`).
- **Fallbacks**: if tiPG MVT performance is insufficient for large layers, **Martin** can serve the same `pub` views/functions. The adapter type `tipg-vector` would gain a sibling `martin-vector`, and manifests stay otherwise identical.

---

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| tiPG endpoint/path changes between versions | Broken tile URLs | Pin the version. URL building lives in one adapter. Phase 1 spike documents the paths |
| Catalog refresh lag after new views | Project appears but tiles 404 | Migrator runs before tiPG, documented refresh step in `mapgen apply`, short TTL in dev |
| Function collections not supported on the tile endpoint as expected | Parametrized layers limited | Spike in Phase 1. Fallback: materialized variants or Martin function sources |
| Workers creating arbitrary DB objects | Security/data integrity | `SECURITY DEFINER` publish function. Workers own only `ml_out` |
| MCP DDL misuse | Schema damage | DDL only via reviewed SQL files + migrator. Confirmation gate on apply |
| RDS PostGIS version drift from local (Phase 6) | Behavior differences | Pin the local PostGIS image to a version RDS for PostgreSQL offers |
| Data imported without a recipe is lost on `reset-db` | Silent data loss | `make import` prints a recipe stub after every ad hoc import. `reset-db` lists datasets with no recipe and requires confirmation. Backup offered first |
| CRLF line endings / Windows-side editing on WSL | Scripts fail with `\r` errors | `.gitattributes` forcing LF. Repo on the Linux filesystem. Troubleshooting entry |
| GDAL image vs PostGIS PROJ version differences | Subtle CRS transform differences | Reproject in ogr2ogr (single PROJ), store 4326 by default, and record source CRS in `app.datasets` |
| Python wheels bundling their own GDAL (rasterio/pyogrio) | R, Python, and CLI disagree on drivers or PROJ grids | `--no-binary` builds against system GDAL. The Phase 1 exit gate checks that the versions match |
| Large geotools image / slow first build on WSL | Friction on install/reinstall | Separate `make build-tools` step, pinned base, `make nuke` keeps this image unless `all=1` |

---

## 8. Decisions (confirmed, rev 3)

| # | Decision | Outcome | When it matters |
|---|---|---|---|
| 1 | Migration tool | **dbmate**. Schema only; data via recipes, project views via `mapgen apply` | Phase 1 |
| 2 | Reverse proxy | **Caddy**. Local only, replaced by ALB/CloudFront in Phase 6 | Phase 1 |
| 3 | IaC | **Terraform** | Phase 6 only |
| 4 | Cloud database | **RDS for PostgreSQL**. Local PostGIS version pinned to one RDS offers | Pin in Phase 1, used in Phase 6 |
| 5 | Seed/demo data | **Natural Earth**, loaded through the import recipes | Phase 1 |
| 6 | Frontend | **SvelteKit (Svelte 5), `adapter-static`** | Phase 2 |
| 7 | GDAL runtime | **`geotools` image: GDAL + R + Python 3 on one GDAL/PROJ build**, and the base for the Phase 5 workers | Phase 1 |
| 8 | Operator control surface | **GNU Make** | Phase 1 |
| 9 | Cloud scope | **No AWS in Phases 1–5.** Migration-friendly posture only (§5.1) | Phases 1–5 |

No open decisions block Phase 1. Version pins (PostGIS, tiPG, rocker/geospatial, Caddy) are chosen at the start of Phase 1 and recorded in an ADR.

---

## 9. Next Step

**STOP. Awaiting confirmation before executing Phase 1.** On approval, Phase 1 runs in this order:
1. `compose.yaml` + networks + `Makefile` skeleton + `docs/setup/01-02`
2. DB migrations (schemas, roles, `app.datasets`)
3. `geotools` image (GDAL + R + Python 3, version-match check) + `scripts/import.sh` + Natural Earth recipes + `docs/setup/04`
4. Placeholder `pub` views + tiPG + proxy + the tiPG spike (ADR in `docs/decisions/`)
5. Backup/reset/nuke targets + `docs/setup/03` + `99`, then the clean-clone walkthrough and `make verify`
