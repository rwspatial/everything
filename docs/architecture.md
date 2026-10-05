# Architecture

Living diagrams of the stack: what runs **today**, and what the plans in `.claude/plans/` **propose**.
Update this file in the same change that adds or removes a service, route, layer adapter or project.
`make arch-check` (also run by `make verify`) fails if a compose service, adapter type or project is missing here.

Diagrams are [Mermaid](https://mermaid.js.org/). GitHub renders them. In VS Code, install
*Markdown Preview Mermaid Support* (`bierner.markdown-mermaid`) and open the preview (Ctrl+Shift+V).

Key: solid = running today · amber = wired but has no data yet · dashed grey = proposed.

## 1. Runtime today

Everything the browser loads comes through the proxy on `:8080`, except the basemaps, which it fetches straight from
their public hosts.

```mermaid
flowchart LR
  classDef empty fill:#fff4d6,stroke:#d49a00,color:#5c4200
  classDef ext fill:#eef2f7,stroke:#8a99ad,color:#334

  browser["Browser<br/>Svelte + MapLibre"]

  subgraph web["proxy (Caddy :8080)"]
    r_app["/ (app)"]
    r_proj["/api/projects (registry)<br/>/projects/*.json (fallback)"]
    r_tiles["/tiles/*"]
    r_raster["/raster/*"]
    r_admin["/admin, /api/admin/*<br/>(forward_auth; wizard at /admin/new)"]
  end

  frontend["frontend<br/>static Svelte build"]
  projects[("projects/&lt;slug&gt;/project.json<br/>bind mount")]
  tipg["tipg<br/>OGC Features + MVT tiles"]
  titiler["titiler<br/>COG tiles + pixel values"]
  cog[("data/cog/*.tif<br/>maine/phzm_2023_min_temp")]
  core_api["core-api<br/>FastAPI: projects + admin API"]

  subgraph db["postgis"]
    pub[("pub.* views<br/>world_overview__*, maine_*__*, …")]
    src[("src_* tables<br/>Natural Earth, Maine, Census")]
    app[("app.* registry<br/>projects, recipes, runs")]
  end

  basemaps["OSM, Esri imagery,<br/>OpenFreeMap"]:::ext

  browser --> r_app --> frontend
  browser --> r_proj --> core_api
  r_proj -.->|core-api down| projects
  browser --> r_tiles --> tipg -->|"role tipg_ro, schema pub only"| pub
  browser --> r_raster --> titiler --> cog
  browser --> r_admin --> core_api --> app
  browser -.->|basemap tiles| basemaps
  pub -->|SELECT from| src
```

## 2. Data pipeline today (offline, run by `make`)

Nothing on the web side writes data. Data comes in through the tool containers, and the website only reads it.

```mermaid
flowchart LR
  classDef ext fill:#eef2f7,stroke:#8a99ad,color:#334

  upstream["Upstream sources<br/>Natural Earth, Maine GeoLibrary,<br/>USFWS NWI, EPA ATTAINS, USWTDB, …"]:::ext
  recipes["data/recipes/*.yaml"]
  migrator["migrator (dbmate)<br/>db/migrations"]
  geotools["geotools<br/>scripts/geoimport.py (ogr2ogr)"]
  seed["make seed<br/>db/seed/*.sql"]

  subgraph postgis
    src[("src_* tables")]
    pub[("pub.* views")]
    app[("app.datasets / recipes / runs")]
  end

  tipg["tipg<br/>(make refresh re-reads catalog)"]

  migrator -->|schemas, roles, grants| postgis
  recipes --> geotools
  upstream -->|download| geotools
  geotools -->|import-recipe / import-all| src
  geotools -->|run log, health, freshness| app
  seed -->|CREATE OR REPLACE VIEW| pub
  pub --> tipg
```

**Maine data:** the Maine vector recipes (`me_*`, `nwi_me`, `attains_*`, `uswtdb_me`, `phzm_2023_zones_me`) load into
`src_*` and are published as `pub.maine_*` views (`db/seed/030`–`060`) on four draft projects: maine-coast,
maine-water, maine-lands and maine-infrastructure. The raster recipe `phzm_2023_grid_me` (`kind: raster`) writes a
validated COG to `data/cog/maine/phzm_2023_min_temp.tif`, which titiler serves to maine-lands.

A raster layer loads the same way, but through `/raster/<name>/{z}/{x}/{y}.png` → titiler, which reads the COG
from `data/cog/` (the proxy pins `url=`). Clicking a raster layer asks `/raster/<name>/point/<lon>,<lat>` for the
pixel value shown in the Inspector.

## 3. How one map layer loads

```mermaid
sequenceDiagram
  participant B as Browser (Viewer.svelte)
  participant P as proxy
  participant T as tipg
  participant DB as postgis

  B->>P: GET /api/projects, then /api/projects/world-overview (static /projects/*.json if core-api is down)
  P-->>B: layer specs (source.type = tipg-vector, collection = pub.world_overview__countries)
  Note over B: adapters.ts turns each spec into a MapLibre source + style layers
  loop every visible tile while panning or zooming
    B->>P: GET /tiles/collections/pub.world_overview__countries/tiles/WebMercatorQuad/{z}/{x}/{y}
    P->>T: same path, /tiles prefix stripped
    T->>DB: ST_AsMVT(...) over the pub view, clipped to the tile
    DB-->>T: MVT bytes
    T-->>B: vector tile, layer "default"
  end
  Note over B: MapLibre draws the features and styles them in the browser from project.json paint rules
```

Layer adapters (`frontend/src/lib/adapters.ts`), one per `source.type`:

| Adapter | Fetches from | Used today by |
|---|---|---|
| `tipg-vector` | `/tiles/collections/<pub view>/tiles/…` (MVT) | world-overview, analysis-sandbox, maine-coast, maine-water, maine-lands, maine-infrastructure, maine-overview, maine-terrain, maine-places, maine-soils, maine-facilities, maine-energy, maine-transportation, maine-habitat, maine-broadband |
| `geojson-url` | any GeoJSON URL | nothing yet |
| `raster-xyz` | any XYZ raster tile URL | analysis-sandbox (stub) |
| `raster-cog` | `/raster/<name>/{z}/{x}/{y}.png` (titiler) | maine-lands (hardiness temperature grid), maine-terrain (elevation, hillshade, slope), maine-soils (hydrologic soil group grid), maine-landcover (NLCD 2025, Cropland Data Layer 2025, LANDFIRE vegetation and fuels; categorical) |

## 4. Proposed

Drawn from the `maine-projects`, `maine-etl-catalog`, `admin-dashboard` and `spatial-app-architecture` plans.

```mermaid
flowchart LR
  classDef now fill:#e8f4ea,stroke:#3c8a4a,color:#1d3d22
  classDef todo fill:#f4f4f4,stroke:#999,stroke-dasharray:5 4,color:#555

  subgraph today["Today"]
    tipg["tipg"]:::now
    titiler["titiler"]:::now
    postgis[("postgis")]:::now
    core_api["core-api"]:::now
    geotools["geotools"]:::now
    maine_proj["projects/maine-*<br/>14 draft manifests"]:::now
    census["Census API recipes<br/>kind: table (ACS 5-yr)"]:::now
    mapgen["mapgen + /admin/new<br/>(Phase 3 project creator)"]:::now
    mcp_db["mcp-db: spatial-db MCP server<br/>(read-only, role mcp_ro)"]:::now
    mcp_pipe["mcp-pipeline: project-pipeline MCP<br/>(files + scoped core-api token)"]:::now
    worker["worker: R + Python processes<br/>(app.jobs queue, ml_out → pub)"]:::now
    dataset_worker["dataset-worker: re-download, import,<br/>update + health checks (scheduler)"]:::now
    mcp_an["mcp-analysis: analysis MCP<br/>(jobs via core-api token)"]:::now
    cogs[("data/cog/maine/*.tif<br/>+ provenance sidecars")]:::now
  end

  maine_views[("more pub.maine_* views<br/>counties, tracts, habitat, …")]:::todo
  rasters["More raster recipes<br/>LANDFIRE, SNODAS, VIIRS"]:::todo
  zonal["Zonal stats → vector tables<br/>(NDVI per town)"]:::todo
  pmtiles["PMTiles for heavy layers<br/>(soils fallback)"]:::todo
  more_procs["More processes: kriging → COG,<br/>zonal stats, ML models"]:::todo
  aws["AWS (Phase 6): CloudFront + ALB,<br/>RDS PostGIS, S3 COGs"]:::todo

  census --> geotools
  geotools --> maine_views
  maine_views --> postgis
  postgis --> tipg --> maine_proj
  rasters --> geotools --> cogs --> titiler --> maine_proj
  cogs --> zonal --> postgis
  core_api -->|"app.jobs"| worker -->|"ml_out → pub.analysis_sandbox__job_*"| postgis
  core_api -->|"app.jobs (dataset)"| dataset_worker -->|"geoimport.py"| postgis
  more_procs -.-> worker
  mcp_an -->|"processes, jobs"| core_api
  postgis -.-> pmtiles
  mcp_db -->|"SELECT pub, src_*"| postgis
  mcp_pipe -->|"validate, stats"| core_api
  mcp_pipe -->|"proposes files; person runs mapgen apply"| mapgen
  mapgen --> maine_proj
  today -.->|later| aws
```

## Project creation (Phase 3)

One contract, two front doors, one registry:

- `contracts/project-manifest.v1.schema.json` is the manifest contract. The frontend's types are generated from it
  (`make contracts`, checked by `make verify`), and `contracts/validate.py` checks a manifest against it, against status
  rules, and against the live database (the view exists, tiPG can read it, one geometry column with an SRID, an `id`
  column, a GiST index, field names in popups and styles). The MapLibre style spec is checked by
  `frontend/scripts/validate-styles.mjs`.
- `./mapgen` (CLI, in geotools): `new` scaffolds `projects/<slug>/` from a template, `apply` runs its SQL through the
  migrator (so tiPG's grants apply), refreshes tiPG and registers it; `sync` registers every file.
- `/admin/new` (browser): pick a `pub` view, a style preset (single, categorical, quantile choropleth, graduated
  circles, heatmap; breaks computed in PostGIS), preview, save through core-api. `./mapgen export` writes it to git.
- `app.projects` + `app.manifest_versions` hold what is served; files in `projects/` stay the source of truth in git.

## Services

| Service | Role | Profile |
|---|---|---|
| postgis | Database: `src_*` raw imports, `pub.*` published views, `app.*` registry | default |
| migrator | dbmate: applies `db/migrations`, sets role passwords, then exits | default |
| tipg | Serves `pub.*` views as OGC API Features and vector tiles | default |
| titiler | Serves COGs under `data/cog/` as raster tiles | default |
| core-api | Project registry (`/api/projects`, public reads; `/api/admin/projects`, writes), admin API (`/api/admin/*`) and the auth check for `/admin` | default |
| frontend | Static Svelte build served by Caddy | default |
| proxy | Caddy: the only published port (`:8080`), routes everything | default |
| geotools | GDAL + Python + R: imports, raster work, registry updates | tools |
| node | Frontend install, dev server, type check | tools |
| e2e | Playwright browser tests (`make e2e`) | test |
| mcp-db | spatial-db MCP server for Claude Code: read-only `pub` + `src_*` as role `mcp_ro`, stdio via `.mcp.json` | mcp |
| mcp-pipeline | project-pipeline MCP server: validates via core-api (scoped token), writes only `projects/`, returns `./mapgen apply` | mcp |
| mcp-analysis | analysis MCP server: lists processes, submits and follows jobs via core-api (scoped token) | mcp |
| worker | Analysis worker (FROM geotools): claims `app.jobs`, runs R and Python processes, publishes `pub.analysis_sandbox__job_<id>` | workers |
| dataset-worker | Dataset jobs from the dashboard and its scheduler (update checks, re-download, import, health, enable/disable) via `scripts/geoimport.py`, as `loader` | workers |
