# Maine Project Family — Plan

Status: **DRAFT — awaiting confirmation. No code written.**
Date: 2026-09-29
Builds on: `.claude/plans/spatial-app-architecture.plan.md` (Phases 1–2 done). Mirrors the existing conventions exactly
(recipes → `src_*` → `db/seed` views → `projects/<slug>/project.json`), extending them minimally where rasters and API pulls need it.

## Verified today (live checks, 2026-09-29)

| Fact | Evidence |
|---|---|
| Maine county subdivisions: **529** (430 towns [LSAD 43], 42 unorganized territories "UT" [46], 29 plantations [39], 23 cities [25], 5 other) in **16 counties** | Parsed `cb_2024_23_cousub_500k.zip` (0.37 MB) |
| TIGER 2024/2025 Maine files: cousub 3.6 MB, tract 3.1 MB, block group 5.4 MB; national CB counties 11.6 MB | HTTP HEAD on www2.census.gov |
| **Census API now requires a key**: keyless ACS requests 302-redirect to `missing_key.html` | `api.census.gov/data/2024/acs/acs5?...` |
| ACS 5-year **2024** (2020–2024) dataset is published | `/data/2024/acs/acs5.json` → 200 |
| 3DEP 1/3″ DEM tiles are COGs on public S3, **0.33–0.48 GB per 1°×1° tile** (~17–20 tiles cover Maine, ~7 GB if downloaded whole) | `prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/n45w070/…` |
| 3DEP **1 m** DEM: **1,795 tiles** intersect the Maine bbox, ~390 MB each (≈ 700 GB) | TNM Access API |
| Sentinel-2 L2A on Earth Search (public, no auth): **1,265** scenes over Maine Jun–Aug 2025, **404** with < 20 % cloud; `red`, `nir`, `scl` COG assets | STAC search |
| SSURGO Maine: **20 survey areas, 1,864 map units, 434,738 polygons**; last refresh 2025-08-29 | Soil Data Access SQL |
| Authoritative MEGIS town/township polygons: ArcGIS FeatureServer owned by a `@maine.gov` account in org `RbMX0mRVOFNTdLzd` (Maine GeoLibrary) | ArcGIS search |
| **titiler is not wired up**: `compose.yaml` only mentions it in a network comment; no service, no Caddy route | repo grep |

Items marked *(verify at phase start)* below were not checked today.

---

## 0. Existing conventions this plan mirrors

- **Recipes** `data/recipes/<name>.yaml`, keys today: `name, description, source{url|path, layer}, target, srs, src_srs, mode, fix_invalid, clip_web_mercator, open_options, license, notes, enabled, todo`. Run by `scripts/geoimport.py` (`make import-recipe r=…`, `make import-all`). `make reset-db` replays all enabled recipes.
- **Source schemas** created by migration: `CALL app.ensure_src_schema('src_<domain>')`.
- **Published views** `pub.<project_slug_with_underscores>__<layer>` in `db/seed/NNN_<project>.sql` (`CREATE OR REPLACE`), functions `SECURITY DEFINER`.
- **Projects** `projects/<slug>/project.json` + `projects/index.json`; layer adapters `tipg-vector | tipg-geojson | geojson-url | raster-xyz`; legends `categorical | gradient | single | none`; `controls` for function params; `status: todo` for pending layers.
- **Storage CRS** EPSG:4326 for vectors (importer default); `make cog` writes COGs to `data/cog/` (gitignored).
- **Verification**: `make verify` (scripts/verify.sh + verify_tools.py) and `make e2e` (Playwright).

---

## 1. Project family (recommended over one mega-project)

| Slug | Phase | Contents | Status at first ship |
|---|---|---|---|
| `maine-overview` | A, A2 | Towns (county subdivisions) with ACS attributes, counties, tracts, block groups | draft |
| `maine-terrain` | B | Hillshade, elevation tint, slope, contours | draft |
| `maine-soils` | C | SSURGO: hydrologic soil group, drainage, farmland class, water-table depth | draft |
| `maine-vegetation` | D | Growing-season NDVI 2025 (+ mean NDVI per town) | draft |
| `maine-context` | E (optional) | MEGIS towns and UT townships, conserved lands, NHD HR hydrography, NLCD | stub, with to-do layers from day one |

**Why a family:** each map stays fast and focused, phases ship independently, and the hub already groups projects
(all share the `maine` tag). The alternative, one project with ~20 layers, makes the layer list unwieldy and mixes heavy
raster and vector loads.

**Shared view:** `center [-69.25, 45.3]`, `zoom 6.2`, `bounds [-71.1, 42.95, -66.9, 47.47]` (the viewer already honours
`view.bounds`), basemap `positron`; terrain and vegetation default to `aerial-labels`.

**County → town drill-down:** counties visible at all zooms (outline and label), towns `minzoom 7`, tracts and block groups
`minzoom 9` and off by default. Add one generic viewer feature, `interaction.zoomTo: true` (clicking a feature fits the map
to its bbox). Every project benefits, not just Maine.

---

## 2. Layer inventory

Legend: **V** = vector (PostGIS → tiPG), **R** = raster (COG → titiler), **T** = table (joined in a view).

| # | Layer | Source / access | License | Format | Download | Resolution / scale | Update | Type → target |
|---|---|---|---|---|---|---|---|---|
| C1 | Counties | Census cartographic boundary `GENZ2024/shp/cb_2024_us_county_500k.zip`, filtered `STATEFP='23'` | Public domain | SHP (zip) | 11.6 MB (national) | 1:500k | Annual | V → `src_census.counties` |
| C2 | **County subdivisions** (towns, plantations, cities, UTs) | `GENZ2024/shp/cb_2024_23_cousub_500k.zip` (display); `TIGER2024/COUSUB/tl_2024_23_cousub.zip` (full detail, later) | PD | SHP | 0.37 MB / 3.6 MB | 1:500k / ~1:24k | Annual | V → `src_census.cousub` |
| C3 | Tracts, block groups | `TIGER2024/TRACT/tl_2024_23_tract.zip`, `TIGER2024/BG/tl_2024_23_bg.zip` (or CB 500k equivalents) | PD | SHP | 3.1 MB, 5.4 MB | ~1:24k | Annual | V → `src_census.tracts`, `.block_groups` |
| C4 | **ACS 5-year 2020–2024** | `https://api.census.gov/data/2024/acs/acs5?get=…&for=county subdivision:*&in=state:23 county:*` (also county, tract, block group) — **API key required** | PD | JSON | < 1 MB per geography | per geography | Annual (December) | T → `src_census.acs5_2024_<geo>`, joined on GEOID |
| T1 | DEM 1/3″ (3DEP) | Public S3 COGs `…/Elevation/13/TIFF/current/n{lat}w{lon}/USGS_13_…tif`, read windowed via `/vsicurl/` | PD (credit "USGS 3DEP") | COG | ~7 GB if downloaded; much less read windowed | ~10 m | Irregular | R → `data/cog/maine/dem_10m.tif` |
| T2 | Hillshade, slope | Derived from T1 (`gdaldem`) | PD | COG | – (≈0.5 GB, ≈0.8 GB) | 10 m | With T1 | R |
| T3 | Contours | Derived from T1 (`gdal_contour` on a 30 m aggregate) | PD | → PostGIS | – | 50 ft interval | With T1 | V → `src_terrain.contours_50ft` |
| T4 | 1 m lidar DEM | TNM API "DEM 1 meter", 1,795 tiles | PD | GeoTIFF | ≈ 700 GB statewide | 1 m | Project-based | **Area-of-interest only, not statewide** |
| V1 | **NDVI, Sentinel-2 L2A** (recommended) | Earth Search STAC `sentinel-2-l2a` (public COGs, no auth) | Copernicus: free, attribution required | COG (red, nir/nir08, scl) | ~10–30 GB network *read* (not stored) | 10 m (20 m default) | 5-day revisit | R → `data/cog/maine/ndvi_2025_jja_20m.tif` |
| V2 | NDVI, Landsat C2 L2 | Earth Search `landsat-c2-l2` *(verify: assets point at a requester-pays USGS bucket)* or Planetary Computer (free, signed URLs) | PD | COG | ~3–8 GB read | 30 m | 8-day (L8 + L9) | R (fallback) |
| V3 | NDVI, MODIS MOD13Q1 | Planetary Computer `modis-13Q1-061` (free, signed) or LP DAAC (Earthdata login) | PD | COG/HDF | < 100 MB | 250 m | 16-day composites | R (smoke test / context) |
| S1 | **SSURGO soils** | Spatial: Web Soil Survey per-area zips (20 areas; exact scripted URL *verify at Phase C*) **or** gSSURGO Maine FileGDB (NRCS Box, manual download). Tabular: Soil Data Access REST SQL (scriptable, verified) | PD (cite USDA-NRCS) | SHP / FileGDB + tables | ~0.5–1.5 GB *(verify)* | 1:12k–1:24k | Annual (Oct) | V → `src_soils.mupolygon` (+ `muaggatt`, `mapunit`) |
| X1 | **MEGIS towns and townships** (splits UTs into individual townships) | Maine GeoLibrary FeatureServer (`services1.arcgis.com/RbMX0mRVOFNTdLzd/.../Maine_Town_and_Townships_Boundary_Polygons_Feature`), read by GDAL's ESRIJSON driver with paging | Maine GeoLibrary terms *(verify)* | ESRI JSON | ~10–40 MB | ~1:24k | As needed | V → `src_maine.towns_townships` |
| X2 | **Conserved lands** | Maine GeoLibrary / MNAP FeatureServer *(verify item)* | *(verify)* | ESRI JSON | ~20–60 MB | parcel | Periodic | V |
| X3 | **NHDPlus HR** (flowlines, waterbodies) | USGS TNM, HU4 0101–0106 FileGDBs | PD | FileGDB | ~0.5–1.5 GB each | 1:24k | Irregular | V → `src_hydro.*` (feeds `hydrology-sketch` too) |
| X4 | **NLCD / Annual NLCD** land cover | MRLC (CONUS 30 m; clip to Maine) *(verify URL)* | PD | GeoTIFF | 1–2 GB CONUS per year | 30 m | Annual | R |
| X5 | Coastline | TIGER coastline or MEGIS coastline | PD | SHP | small | 1:24k–1:500k | – | V |

**Most valuable of the Maine-specific extras:**
- **X1 MEGIS townships:** the unorganized territory is ~half of Maine's area, and Census lumps it into 42 UTs.
- **X2 conserved lands:** a large share of Maine is conserved, and the layer is often asked for.
- **X3 NHD HR:** Maine is water-dominated, and it upgrades `hydrology-sketch`.
- **X4 NLCD:** the context NDVI needs.
- **1 m lidar:** later, for specific areas only.

---

## 3. Architecture additions

### 3.1 Raster serving: add titiler (not wired today)

**Compose** gets a new `titiler` service:
- Image `ghcr.io/developmentseed/titiler:<pin at Phase B>`.
- Networks: `[api]` only, since it never needs PostGIS.
- Volume `./data/cog:/data/cog:ro`.
- Env `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`, `GDAL_CACHEMAX=512`, `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif`.
- Healthcheck on `/healthz`.

**Caddy** gets a new `handle_path /raster/*` route that exposes **named rasters only**:
- `/raster/<name>/{z}/{x}/{y}.png?rescale=…&colormap_name=…` → titiler `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=/data/cog/<name>.tif&…`
- `/raster/<name>/point/{lon},{lat}` → `/cog/point/…`, used for click-to-inspect values.
- `/raster/<name>/info` → `/cog/info`
- The client's own `url=` parameter is stripped (`uri query -url`). Without this, titiler would fetch *any* URL, which is SSRF-prone. Only files under `data/cog/` are reachable.

**Why not PostGIS raster:**
- tiPG cannot serve it.
- titiler reads COG byte ranges directly.
- PostGIS rasters would bloat the DB volume, slowing every backup and reset.

Where SQL needs raster values (e.g. mean NDVI per town), geotools computes zonal statistics (`rasterstats`/`exactextract`) and writes the numbers into a vector table instead. No PostGIS raster is planned.

**Alternative considered:** pre-rendered PNG tiles (`gdal2tiles`) served by Caddy. That needs no new service, but loses dynamic colour ramps and point queries. Keep it in reserve for hillshade if titiler ever becomes a bottleneck.

**Phase 6 note:** titiler maps onto Lambda or Fargate reading COGs from S3, so this stays migration-friendly.

### 3.2 Frontend additions (generic; every project benefits)

- **New adapter `raster-cog`:**
  ```json
  { "type": "raster-cog", "cog": "maine/ndvi_2025_jja_20m", "rescale": [-0.2, 0.9], "colormap": "rdylgn", "nodata": -32768 }
  ```
  It builds `/raster/<cog>/{z}/{x}/{y}.png?...` tiles. It's one registry entry, as the adapter design intended (plan §2.2).
- **Raster click values:** the inspector calls `/raster/<cog>/point/{lon},{lat}` and shows e.g. "NDVI 0.71" or "Elevation 312 m".
- **`interaction.zoomTo`:** click to fit a feature, for the drill-down.
- **Classed choropleths:** MapLibre `step` expressions plus a `categorical` legend, both of which exist today. Breaks come from a new helper, `make breaks v=pub.maine_overview__towns f=median_hh_income n=5 method=quantile|jenks`. It prints ready-to-paste `style` + `legend` JSON; Phase 3's `/stats` endpoint automates it later.
- **Colour ramps:**
  - NDVI: diverging brown → yellow → green, with water/negative values blue-grey (`gradient` legend).
  - Soils: fixed categorical palettes. Hydrologic soil group A, B, C, D plus dual groups A/D, B/D, C/D. Drainage class uses 7 ordered classes on a sequential ramp. Farmland class has 4 main classes plus "not prime".
  - Census: 5-class sequential ramps (YlGnBu for income, Purples for age, and so on).
- **Attribution:** `LayerSpec.attribution` already flows into MapLibre's attribution control. Each Maine layer sets its credit text (see §5).

### 3.3 CRS strategy

| Purpose | CRS | Where it happens |
|---|---|---|
| Vector storage | **EPSG:4326** (repo convention) | `ogr2ogr -t_srs` at import |
| Analysis (area, distance, zonal stats, slope) | **EPSG:26919** NAD83 / UTM 19N (all of Maine lies in zone 19, −72° to −66°) | `ST_Transform(geom, 26919)` in analysis views. For heavy tables (soils, contours) a stored `geom_utm` column + GiST, from a new recipe key `analysis_srs` |
| Raster storage | **EPSG:26919** (true metres, so correct slope and hillshade). Sentinel-2 is natively UTM 19N/WGS84 (EPSG:32619), so NDVI only shifts datum (~1 m) | `gdalwarp -t_srs EPSG:26919` once, at derivation |
| Display | EPSG:3857 Web Mercator | At serve time only: tiPG per vector tile, titiler per raster tile. Never in the browser |

### 3.4 Disk layout (all already gitignored via `data/cache/*`, `data/cog/*`)

```
data/cache/downloads/maine/…      raw downloads (zips, GDBs), kept for offline re-runs
data/cache/work/maine/…           intermediates (VRTs, per-tile composites); safe to delete
data/cog/maine/<name>.tif         published COGs
data/cog/maine/<name>.json        provenance sidecar (sources, checksums, parameters, date, license)
```

Estimated persistent footprint:

| Item | Size |
|---|---|
| DEM 10 m | ~1.5–2.5 GB |
| Hillshade | ~0.3–0.6 GB |
| Slope | ~0.8 GB |
| NDVI 20 m | ~0.4–0.8 GB |
| DB growth (contours, soils) | ~2–3 GB |
| **Total** | **~5–8 GB** |
| Peak working space during NDVI/DEM builds | ~15 GB |

Add a note to 99-troubleshooting: WSL's virtual disk grows and doesn't shrink on its own (`wsl --manage <distro> --set-sparse true`, or compact it).

`.gitignore` needs **no change** (it's covered). I'll add an explicit comment line so it's obvious.

### 3.5 Recipe format: minimal extensions

**New keys**, validated in `RECIPE_KEYS`:

| Key | Values | Purpose |
|---|---|---|
| `kind` | `vector` (default) \| `table` \| `raster` | Selects the import path |
| `group` | e.g. `maine` | `make import-all g=maine` runs one family |
| `depends_on` | `[recipe, …]` | `import-all` runs in dependency order; derivations name their inputs |
| `where` | OGR SQL filter | → `ogr2ogr -where` (e.g. `STATEFP = '23'` on the national county file) |
| `analysis_srs` | e.g. `EPSG:26919` | Adds and populates an indexed `geom_utm` column |
| `source.census_api` | `{year, dataset, get: […], for, in}` | `kind: table`. The key comes from `CENSUS_API_KEY` in `.env`, never from the recipe |
| `source.sda` | `{query}` | `kind: table`. Soil Data Access SQL |
| `source.urls` / `source.stac` | list of COG URLs / `{api, collection, bbox, datetime, query, assets}` | `kind: raster` |
| `source.recipe` | name | Derive from another recipe's output |
| `resolution`, `resampling`, `cutline` | numbers / names | Raster output grid; `cutline` is a src table or recipe |
| `steps` | ordered list of `{op, …args}` | Operation registry: `warp`, `hillshade`, `slope`, `contours` (→ vector table), `ndvi_composite`, `scale_int16` |

**Rules:**
- `import-all` **skips `kind: raster`** unless `rasters=1`. COGs live on disk, survive `reset-db`, and are expensive to rebuild. `make reset-db` therefore only replays vector and table recipes.
- Raster provenance goes in the sidecar JSON, not `app.datasets`. That table is limited to `src_*` tables, and rasters outlive database resets. `make datasets` also lists `data/cog/**/*.json`.
- Non-spatial tables get an `app.datasets` row with NULL geometry fields (the columns are already nullable). `post_import` skips geometry checks for `kind: table`.
- Each `op` is one small function (probably a new `scripts/rasterops.py` imported by `geoimport.py`), not a one-off script per dataset.

**Example recipes (illustrative):**
```yaml
# data/recipes/me_cousub.yaml   (Phase A)
name: me_cousub
group: maine
source: { url: https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_23_cousub_500k.zip }
target: src_census.cousub
license: Public domain (U.S. Census Bureau)
enabled: true
---
# data/recipes/me_acs5_2024_cousub.yaml   (Phase A)
name: me_acs5_2024_cousub
kind: table
group: maine
source:
  census_api: { year: 2024, dataset: acs/acs5, get: [NAME, B01003_001E, B19013_001E, B19013_001M],
                for: "county subdivision:*", in: "state:23 county:*" }
target: src_census.acs5_2024_cousub
license: Public domain (U.S. Census Bureau, ACS 5-year 2020–2024)
enabled: true
---
# data/recipes/me_dem_10m.yaml   (Phase B)
name: me_dem_10m
kind: raster
group: maine
depends_on: [me_state_outline]
source: { urls: [ "/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/n45w070/USGS_13_n45w070.tif", "…" ] }
target: cog:maine/dem_10m
srs: EPSG:26919
resolution: 10
resampling: bilinear
cutline: { table: src_census.state_outline, buffer_m: 500 }
license: Public domain (USGS 3DEP)
---
# data/recipes/me_hillshade_10m.yaml   (Phase B)
name: me_hillshade_10m
kind: raster
group: maine
depends_on: [me_dem_10m]
source: { recipe: me_dem_10m }
target: cog:maine/hillshade_10m
steps: [ { op: hillshade, multidirectional: true, z_factor: 1 } ]
```

### 3.6 Database: migrations and seeds

- Migration `…_maine_sources.sql`: `CALL app.ensure_src_schema('src_census')`, `('src_terrain')`, `('src_soils')`, `('src_maine')`.
- Seeds, following the `NNN_<project>.sql` pattern:
  - `030_maine_overview.sql`
  - `040_maine_terrain.sql` (contours)
  - `050_maine_soils.sql`
  - `060_maine_vegetation.sql` (NDVI zonal stats per town)
- **ACS view rules:**
  - Join on `GEOID`.
  - Map Census sentinel values (−666666666, −999999999, …) to NULL with `NULLIF`/`CASE`.
  - Keep margins of error (`*_M`) for popups.
  - Derive percentages in the view, e.g. broadband share = `B28002_004E / NULLIF(B28002_001E, 0)`.
- **ACS variables** (check against the 2024 `variables.json` at Phase A):

  | Variable | Meaning | Phase |
  |---|---|---|
  | `B01003_001E` | Total population | A |
  | `B19013_001E` | Median household income | A (the one Phase A layer) |
  | `B01002_001E` | Median age | A2 |
  | `B25077_001E` | Median home value | A2 |
  | `B25004_006E` | Seasonal or recreational vacant units (very Maine-relevant) | A2 |
  | `B28002_004E` / `B28002_001E` | Broadband subscriptions / total households | A2 |

- **Maine nuance:** ACS joins at the Census county-subdivision level, where each **UT is one unit** (42 UTs). MEGIS splits the unorganized territory into hundreds of individual townships. So census choropleths use Census geometry, and MEGIS townships (Phase E) are a reference overlay without ACS values.

### 3.7 Soils: data model and what to publish

The SSURGO model runs **map unit → component → horizon**:
- `mapunit` (`mukey`): the polygons in `mupolygon`. A map unit is a *mix* of soils.
- `component` (`cokey`): each soil in the mix, with its share `comppct_r` and a major-component flag.
- `chorizon`: depth layers of each component, holding properties like clay %, organic matter, pH and available water.

Maps need **one value per polygon**, so everything is flattened to `mukey`. NRCS pre-computes this in **`muaggatt`** using standard rules like "dominant condition" and "weighted average".

**Published attributes:**

| Attribute | Source | Meaning |
|---|---|---|
| `hydgrpdcd` | muaggatt | Hydrologic soil group, dominant condition (A–D, A/D…) |
| `drclassdcd` | muaggatt | Drainage class, dominant condition |
| `wtdepannmin` | muaggatt | Min annual depth to water table (cm) |
| `farmlndcl` | mapunit | Farmland classification |
| `aws0100wta` | muaggatt | Available water storage 0–100 cm |
| `slopegradwta` | muaggatt | Weighted slope % |
| `musym`, `muname` | mapunit | Map unit label and name |

Horizon-level aggregation (e.g. depth-weighted clay) is deferred and only needed if an analysis requires it.

**Handling 434,738 polygons:**
- **Detailed layer:** `pub.maine_soils__mapunits` with `minzoom 10`. Polygons are cut with `ST_Subdivide(geom, 256)` into a stored table, which keeps tile clipping fast.
- **Generalized layer** for zooms 6–9: `src_soils.mupolygon_gen`, built by:
  1. `ST_SimplifyPreserveTopology` at 30–50 m in EPSG:26919.
  2. Dissolving adjacent polygons with the same displayed class, per county.
  3. Dropping slivers under ~1 ha.

  Published as `pub.maine_soils__hsg_overview`.
- **Frontend:** two LayerSpecs per theme (overview `maxzoom 10`, detail `minzoom 10`) sharing one legend. This fits tiPG's `TIPG_MAX_FEATURES_PER_TILE=10000`.
- **Fallback if tiles are still slow:** pre-built vector tiles (tippecanoe → PMTiles served by Caddy). This needs no new database service, but adds a build tool.

### 3.8 NDVI options

| Option | Resolution | Access | Statewide Jun–Aug cost | Clouds | License | Verdict |
|---|---|---|---|---|---|---|
| **Sentinel-2 L2A** (Earth Search) | 10 m (B04, B08) / 20 m (B8A) | Public COGs, no auth (verified) | Maine is ~20 MGRS tiles × ~10–20 usable dates. Reading at 20 m via COG overviews ≈ 10–30 GB network, ~30–90 min on a laptop | Per-pixel SCL mask (drop 0, 1, 3, 8, 9, 10, 11), then median | Copernicus, free with attribution | **Recommended** |
| Landsat 8/9 C2 L2 | 30 m | Planetary Computer (free, signed) / USGS (requester-pays on AWS) | ~3–8 GB, faster | QA_PIXEL mask | PD | Fallback / time series back to 2013 |
| MODIS MOD13Q1 | 250 m | Planetary Computer / LP DAAC | Trivial (pre-composited NDVI) | Already composited | PD | Quick smoke test; too coarse for towns |

**Default:** Sentinel-2, growing season **2025-06-01 to 2025-08-31**:
- Cloud-masked (SCL) **median** composite at **20 m**, using B04 resampled plus B8A native 20 m, so resolutions don't mismatch.
- Output EPSG:26919, int16 × 10,000, COG. About 230 M pixels, ~0.5–0.8 GB.
- At ~91,600 km², 20 m is the sweet spot: town-level detail at a quarter of 10 m's read and compute cost.
- The same recipe can run at 10 m for a single county or town via a `bbox` or `cutline` override.
- **Tooling:** add `odc-stac` + `dask` to the geotools requirements (pinned; check GDAL 3.8 compatibility). Composite per MGRS tile, then mosaic.
- **Plus** a vector product: `ndvi_mean` per town (zonal statistics), so NDVI can join the ACS choropleth views.

### 3.9 Verification: generic checks plus per-phase checks

**Generic** (new, and covers every existing and future project):
- `verify.sh` iterates `projects/index.json`. For each non-to-do `tipg-*` layer, it checks the collection is served and a tile at the project's default view contains features.
- For each `raster-cog` layer, `/raster/<cog>/{z}/{x}/{y}.png` must return a non-empty `image/png`.
- `make e2e` gets a data-driven test that opens every project and asserts `renderedCount > 0` for every visible layer.

**Per phase:** see §4.

---

## 4. Phases

### Phase A: one layer end-to-end (towns × median household income)

**Why this one:** it's the cheapest meaningful slice (0.37 MB of geometry plus one API call) and exercises every link:
recipe → `src_*` → seed view → manifest → tiPG → browser.

1. `.env.example`: `CENSUS_API_KEY=` (free signup at `api.census.gov/data/key_signup.html`). geotools gets it via compose env.
2. Recipe extensions, **only** what this phase needs: `kind: table` + `source.census_api`, and `group`.
3. Migration: `src_census`.
4. Recipes `me_cousub`, `me_acs5_2024_cousub`.
5. Seed `030_maine_overview.sql`: `pub.maine_overview__towns` = cousub ⋈ ACS on GEOID, with `name`, `namelsad`, `county`, `lsad`, `pop`, `median_hh_income`, `median_hh_income_moe`.
6. `make breaks` helper → quantile breaks for income.
7. `projects/maine-overview/project.json`: one layer, classed choropleth, legend, popup `"{namelsad}: median household income ${median_hh_income} (±{median_hh_income_moe})"`, Maine view, and to-do layers listing A2 items. Add it to `index.json`.

**Exit gate (`make verify` + `make e2e`):**
- `src_census.cousub` = **529** rows, SRID 4326, GEOIDs unique.
- ACS join: ≥ 95 % of subdivisions have non-null income. The rest must be suppressed or zero-population units, which the check lists.
- tiPG serves `pub.maine_overview__towns`, and a z7 tile over Augusta contains features.
- Browser: the hub shows **Maine Overview**, the viewer renders > 400 town features, the popup shows income, and I review a screenshot.
- The generic per-project checks (§3.9) pass for all projects.

### Phase A2: rest of the Census layers

Counties (C1), tracts and block groups (C3), the remaining ACS variables (switchable), `interaction.zoomTo` drill-down, and census attribution.

**Checks:** 16 counties; tracts and BG counts match TIGER; each ACS view's join coverage; drill-down e2e (click county → zoom level ≥ 8).

### Phase B: terrain (and the raster path)

1. Wire titiler plus the Caddy `/raster/*` named route (§3.1), and the `raster-cog` adapter plus raster point inspect (§3.2).
2. Recipe `kind: raster`, `steps`, `depends_on`, sidecar provenance, and `import-all rasters=1`.
3. Recipes:
   - `me_state_outline`: dissolved from C1.
   - `me_dem_10m`: windowed `/vsicurl/` VRT → `gdalwarp` 26919, 10 m, cutline → COG.
   - `me_hillshade_10m`: multidirectional.
   - `me_slope_10m`: degrees.
   - `me_contours_50ft`: from a 30 m aggregate → `src_terrain`, with `analysis_srs`.
4. `projects/maine-terrain` (default basemap `aerial-labels`).

**Checks:**
- Every COG passes a validity check (`gdalinfo` LAYOUT=COG, or `rio cogeo validate`), is EPSG:26919 with nodata set.
- DEM range plausible: min ≈ −5 m, max ≈ 1,606 m (Katahdin, ±10 m).
- Hillshade values are 0–255.
- `/raster/maine/dem_10m/7/…png` returns 200 PNG.
- A client-supplied `url=` is **ignored** (security check).
- The point query at Katahdin returns > 1,500 m.
- e2e: terrain layers draw, and clicking shows elevation.

### Phase C: soils

1. Choose the spatial source (§6 decision).
2. Recipes: `me_ssurgo_mupolygon` (vector, `analysis_srs`), `me_ssurgo_muaggatt` + `me_ssurgo_mapunit` (`kind: table`, `source.sda`).
3. Seed `050_maine_soils.sql`: the subdivided detail table, the generalized overview, and themed views.
4. `projects/maine-soils`: HSG, drainage, farmland and water-table layers (detail + overview pairs).

**Checks:**
- Polygon count ≈ 434,738 (± refresh drift), and every polygon's `mukey` exists in `muaggatt`.
- HSG values are within {A, B, C, D, A/D, B/D, C/D, NULL}.
- A z7 overview tile has fewer than 10,000 features and a z12 detail tile renders.
- Tile p95 < 300 ms at z8 and z12.

### Phase D: vegetation (NDVI)

1. Add odc-stac/dask to geotools.
2. `ndvi_composite` op and recipe `me_ndvi_2025_jja_20m`.
3. Zonal statistics → `src_maine.town_ndvi`.
4. `projects/maine-vegetation`. Optionally add an `ndvi_mean` layer to `maine-overview`.

**Checks:**
- The COG is valid; values in [−1, 1] after scaling.
- ≥ 97 % of land pixels are valid (not permanently cloud-masked). The check reports gaps.
- Statewide land mean for Jun–Aug is in a plausible range (0.55–0.85).
- Every town has `ndvi_mean`.
- e2e: the layer draws, and a point query over forest returns > 0.6.

### Phase E (optional): Maine context

X1 MEGIS townships, X2 conserved lands, X3 NHD HR, X4 NLCD. Each is one recipe and one view (or COG), added as a to-do layer that gets completed.

---

## 5. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Census API key required** (verified); daily limits and 429s | Phase A import fails | Key in `.env`; one request per geography per recipe (Maine is small); retry with backoff; cache raw JSON in `data/cache/downloads/census/` so `reset-db` doesn't re-hit the API |
| ACS suppression / sentinel values; high MOE in small towns | Misleading choropleth | NULL sentinels; show MOE in popups; legend note "5-year estimates; small-town MOEs are large" |
| UT vs township geography mismatch | Confusion between layers | Census geometry for statistics, MEGIS for reference; documented in layer descriptions |
| **Data volume** (DEM, NDVI reads; soils polygons) | Slow builds, disk | Windowed `/vsicurl/` reads; `rasters=1` opt-in; 20 m NDVI default; soils generalized plus subdivided; footprint ~5–8 GB, documented |
| **SSURGO complexity** (mapunit/component/horizon) | Wrong numbers | Publish NRCS-computed `muaggatt` values only; name the aggregation method in legends ("dominant condition") |
| **NDVI clouds** (coastal fog, summer convection) | Holes / bias | SCL masking + median over 3 months; coverage check; fall back to Landsat to fill gaps, or widen to May–Sep |
| Sentinel-2 processing baseline change (2022 offset of +1000 DN) | Biased NDVI | Earth Search L2A COGs are harmonized *(verify at Phase D)*; otherwise apply `BOA_ADD_OFFSET` from metadata |
| Landsat on AWS is requester-pays | Unexpected AWS charges | Use Planetary Computer for Landsat if chosen |
| titiler SSRF via `url=` | Security | Named-raster Caddy route strips `url`; verify check proves it |
| Raster/vector disk growth inside WSL's virtual disk | Disk exhaustion | Sizes documented; troubleshooting note on compacting |
| MEGIS service URLs/terms change | Broken recipe | Recipes record URL and license; `app.datasets` + sidecars record provenance |

**Attribution text shown on the map** (per-layer `attribution`, which the viewer already shows):
- Census: "U.S. Census Bureau, TIGER/Line & ACS 5-year 2020–2024"
- 3DEP: "USGS 3D Elevation Program"
- Sentinel-2: "Contains modified Copernicus Sentinel data 2025"
- Landsat: "Landsat imagery courtesy of USGS"
- SSURGO: "Soil Survey Staff, NRCS, USDA. SSURGO database for Maine"
- MEGIS: "Maine GeoLibrary / MEGIS"
- NLCD: "MRLC NLCD"
- The Esri basemap credit is already shown.

---

## 6. Decisions needed (recommendations first)

1. **Census API key:** you sign up (free) and put it in `.env` as `CENSUS_API_KEY`. Required before Phase A.
2. **Project family** (4–5 projects, recommended) vs a single `maine` project.
3. **Town geometry:** Census cartographic boundary 1:500k for display (recommended; tiny, generalized), with TIGER full resolution later for analysis.
4. **NDVI default:** Sentinel-2 at 20 m (recommended) vs Landsat 30 m vs 10 m statewide (~4× the cost).
5. **DEM statewide resolution:** 10 m native (recommended, ~2 GB) vs 30 m (~0.3 GB).
6. **SSURGO source:** scripted Web Soil Survey per-area zips (recommended if the Phase C URL check passes) vs a one-time manual gSSURGO download into `data/incoming/`.
7. **Phase E scope:** which of MEGIS townships, conserved lands, NHD HR and NLCD to include (recommend all four, in that order).

**Next step:** on confirmation (plus the API key), start **Phase A only** and stop at its exit gate with a screenshot for review.
