# Maine ETL Catalog — Plan

Status: **E1 + E2 vector datasets loaded 2026-09-30 (13 recipes; see §8). Rasters (E4-E5), Overture (E3), keyed sources (E6) and trails pending.**
Related: `maine-projects.plan.md` (Census/ACS, terrain, soils, NDVI) and `admin-dashboard.plan.md` (registry,
recipe format v2, job queue). Every dataset below is a recipe in `data/recipes/`, tracked in `/admin`, and follows the
same path: recipe → `src_<domain>` → `pub.<project>__<layer>` views (vectors) or `data/cog/maine/...` COGs (rasters)
→ tiPG / titiler → `projects/<slug>/project.json`.

## 1. Verified today (live checks, 2026-09-30)

| Dataset | Finding |
|---|---|
| E911 road centerlines | `services1.arcgis.com/RbMX0mRVOFNTdLzd/.../Maine_E911_Roads_Feature/FeatureServer/0`: **155,257** lines; page size 2,000. The hub also offers a bundled **"Maine E911 Addresses, Roads, Structure, and PSAP FGDB"** |
| E911 address points | `.../Addresses/FeatureServer/0` (E911_NG_Addresses): **792,091** points (397 pages at 2,000 each, so prefer the FGDB bundle) |
| DMR shellfish | `Growing_Area_Boundary` and yearly `…_NSSP_Classifications` services. The newest hosted is **2022 (447 polygons)**; 2017–2022 exist. P90 water-quality score services exist |
| Aquaculture leases | `DMR_Maine_Aquaculture_Leases`: **201** polygons. Also LPA points, applications under review, and denied leases |
| BPL public lands | `Maine_Conserved_Lands_BPL_Interests`: **2,038** polygons; `BPL_Properties_Points_for_MaineFoliage` |
| Boat launches | `Maine_GeoLibrary_Structure/FeatureServer/1` (Maine_Boat_Launches_GeoLibrary): **578** points; also `Lake_Access_AGOL` |
| BPL trails | **Not found** as a statewide state service (only ACAD, SMPDC, DOT walking trails). Needs a source decision (§6) |
| NWI wetlands | `ME_geodatabase_wetlands.zip` **550 MB**, Last-Modified 2026-04-29. The shapefile download is **403** (GDB only) |
| EPA ATTAINS | GIS `gispub.epa.gov/.../OW/ATTAINS_Assessment/MapServer` (points, lines, areas, catchments) is open. The ATTAINS **REST API now returns 401** (key required) |
| US Wind Turbine DB | National shapefile **3.9 MB**, updated 2026-09-28. The API (`energy.usgs.gov/api/uswtdb/v1`) is open: **466 Maine turbines** |
| Overture Maps | Latest release **2026-09-23.1** (monthly), public GeoParquet on S3, no key |
| Plant hardiness (USDA/PRISM 2023) | `prism.oregonstate.edu/phzm/data/2023/phzm_us_grid_2023.zip` **41 MB**; `phzm_us_zones_shp_2023.zip` **7.3 MB** |
| SNODAS | NSIDC G02158 masked CONUS daily tar **21–24 MB/day**, `noaadata.apps.nsidc.org`, **no login** |
| LANDFIRE | LFPS API (`lfps.usgs.gov/api`) is open, no key. Products **LF2025_EVT**, **LF2025_FBFM40** (plus seasonal FBFM40 variants), EVC, EVH; history back to LF2016 |
| VIIRS night lights | NASA Black Marble **VNP46A4** (annual) on LAADS: listing is open, **download needs an Earthdata token** |
| FCC National Broadband Map | BDC public API returns **401 without credentials**: needs a broadbandmap.fcc.gov username + API token |
| TiTiler | **Not wired before today. Now wired and verified** (§2) |

## 2. TiTiler: wired today (done)

- **Compose service `titiler`:** `ghcr.io/developmentseed/titiler:2.4.0`, internal `api` network only, `./data/cog` mounted read-only, healthcheck `/healthz`. The proxy waits for it.
- **Caddy named-raster route** `/raster/<name>/…`:
  - `/{z}/{x}/{y}.png?rescale=&colormap_name=&bidx=` for tiles
  - `/point/{lon},{lat}` for pixel values
  - `/info` for metadata

  The file path is built from the URL and `url=` is **overwritten**, so titiler can only read `data/cog/<name>.tif`. Names allow only `[a-z0-9_/-]`, so no dots and no traversal.
- **Frontend `raster-cog` adapter** in the registry: `{type: "raster-cog", cog: "maine/…", rescale: [a, b], colormap: "…"}`.
- **`make verify`** checks titiler health, a tile, a point value (769 on the test ramp), that `url=` is ignored (SSRF), and that dotted names are rejected. All pass.
- **Still to do for rasters** (Dashboard Phase D): register `cog` / `tile_url` outputs with health checks in `/admin`; paletted COGs for categorical data (§4.3); a date dimension for daily rasters (§4.4); return 404 instead of 500 for missing COG names.

## 3. Inventory

Types: **V** = vector → PostGIS → tiPG; **R** = raster → COG → titiler; **T** = table joined in views.
Key column: **—** means no key.

| # | Dataset | Source / access | Key | License / attribution | Format | Size | Resolution / scale | Update | Type → target |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **E911 road centerlines** | Maine GeoLibrary FeatureServer `Maine_E911_Roads_Feature/0` (paged) **or** the E911 FGDB bundle *(verify URL + terms)* | — | Maine GeoLibrary / Maine E911 Bureau *(verify redistribution terms)* | ESRI JSON / FGDB | ~100–200 MB | Parcel-level, NG911 | Continuous (NG911 maintenance) | V → `src_e911.roads` |
| 2 | **E911 address points** | `Addresses/FeatureServer/0` (792k) or the same FGDB bundle (preferred) | — | same | FGDB | ~150–300 MB | Structure-level points | Continuous | V → `src_e911.addresses` |
| 3 | **DMR shellfish growing-area classifications** | `Growing_Area_Boundary` + newest `…_NSSP_Classifications` (2022 hosted; *verify whether a current/"live" layer exists*) | — | Maine DMR (public) | ESRI JSON | < 10 MB | Growing-area polygons | Annual classification; closures change daily (**not** in these layers) | V → `src_dmr.growing_areas`, `src_dmr.nssp_classifications` |
| 4 | **Aquaculture leases** (+ LPA sites, applications) | `DMR_Maine_Aquaculture_Leases`, `Maine_DMR_Limited_Purpose_Aquaculture_(LPA)_Points`, `AQ_Lease_Apps_Under_Review_POLY_3_view` | — | Maine DMR | ESRI JSON | < 5 MB | Lease polygons / points | Weekly–monthly | V → `src_dmr.aquaculture_*` |
| 5 | **NWI wetlands** | USFWS `ME_geodatabase_wetlands.zip` | — | Public domain (USFWS NWI) | FileGDB (Albers) | **550 MB** zip | 1:24k (Cowardin classes) | Irregular (2026-04-29) | V → `src_nwi.wetlands` + generalized view |
| 6 | **Impaired waters (DEP via EPA ATTAINS)** | ATTAINS GIS MapServer layers (points/lines/areas/catchments) filtered to ME; optional REST API for cause/use detail (**key**) | Optional `EPA_ATTAINS_API_KEY` | Public domain (EPA / Maine DEP) | ESRI JSON | ~20–80 MB | NHDPlus-indexed assessment units | Biennial Integrated Report cycle | V → `src_attains.*` |
| 7 | **BPL public lands** | `Maine_Conserved_Lands_BPL_Interests` (2,038) + `BPL_Properties_Points_for_MaineFoliage` | — | Maine DACF / BPL | ESRI JSON | < 30 MB | Parcel | As needed | V → `src_bpl.lands`, `src_bpl.properties` |
| 8 | **Trails** | **Undecided**: BPL/DACF trail data *(verify with DACF)*, Maine Trail Finder, or OSM `highway=path` via Overture transportation. See §6 | — | depends | – | – | – | – | V → `src_bpl.trails` |
| 9 | **Boat launches** | `Maine_GeoLibrary_Structure/1` (578) + `Lake_Access_AGOL` | — | Maine GeoLibrary / IF&W | ESRI JSON | < 2 MB | Points | Annual | V → `src_bpl.boat_launches` |
| 10 | **US Wind Turbine Database** | USGS national shapefile (3.9 MB) filtered `t_state='ME'` (or the open API) | — | Public domain (USGS/LBNL/ACP) | SHP zip | 3.9 MB | Turbine points | Quarterly | V → `src_energy.wind_turbines` |
| 11 | **Overture buildings + places** | S3 GeoParquet release `2026-09-23.1`, bbox-filtered with **DuckDB** (spatial ext) | — | Buildings: **ODbL** where OSM-derived + CDLA; Places: CDLA-Permissive-2.0. Attribution "© OpenStreetMap contributors, Overture Maps Foundation" | GeoParquet | Maine: ~1 M buildings (~0.3–0.6 GB); places ~100–200k *(estimates)* | Footprints / POIs | Monthly | V → `src_overture.buildings`, `.places` |
| 12 | **USDA plant hardiness zones 2023** | PRISM/OSU `phzm_us_grid_2023.zip` (41 MB) + `phzm_us_zones_shp_2023.zip` (7.3 MB) | — | USDA-ARS / PRISM, OSU (attribution) | GeoTIFF/ASCII + SHP | 48 MB | 800 m grid; half-zone polygons | ~Decadal (2012, 2023) | **R** `maine/phzm_2023` (paletted) + V `src_climate.hardiness_zones` |
| 13 | **SNODAS snow depth + SWE (daily)** | NSIDC G02158 masked daily tar (no login) | — | NOAA NOHRSC / NSIDC (cite) | Flat binary + header in tar | 21–24 MB/day (CONUS) → ~0.1 MB/day per variable clipped to ME | ~1 km (30″) | Daily | **R** time series `maine/snodas/{swe,depth}/YYYY-MM-DD` |
| 14 | **LANDFIRE EVT + FBFM40** (+ seasonal fuels) | LFPS job API: submit AOI (Maine) → poll → zip of GeoTIFF(s) | — | Public domain (USGS/USFS LANDFIRE) | GeoTIFF + VAT (EPSG:5070) | ~50–150 MB each (ME, 30 m) | 30 m | Annual (LF2025) | **R** `maine/landfire/evt_2025`, `fbfm40_2025` (paletted) + T class tables |
| 15 | **VIIRS night lights** | NASA Black Marble VNP46A4 annual via LAADS (tiles over ME, *verify h/v*) **or** EOG VNL v2 (EOG account) | **`EARTHDATA_TOKEN`** | NASA (open; cite Black Marble) | HDF5 tiles | ~tens of MB per year | ~500 m (15″) | Annual | **R** `maine/viirs/vnp46a4_YYYY` |
| 16 | **FCC National Broadband Map (fixed availability)** | BDC public data API: as-of dates → state availability files | **`FCC_BDC_USERNAME` + `FCC_BDC_API_TOKEN`** | FCC public data; **location fabric is licensed (CostQuest), so no point coordinates** | CSV (zipped) per technology | ~100–300 MB for ME *(estimate)* | Location → published as **H3 res-8 hexes / census blocks** | Semiannual (June/December as-of) | T + V (aggregated) → `src_fcc.bdc_fixed`, `pub…broadband_h3` |

**Most valuable, recommended first:**
- E911 roads + addresses: the backbone for any local map.
- DMR classifications + aquaculture: uniquely Maine.
- NWI + ATTAINS: water quality context.
- LANDFIRE EVT: pairs with NDVI and soils.
- FCC broadband: pairs with ACS broadband (B28002) from the Maine plan.

## 4. What the pipeline needs (minimal, reusable)

### 4.1 Source adapters (recipe `source.*`, each one small function in `scripts/etl/ops/`)

| Adapter | Used by | How |
|---|---|---|
| `arcgis_feature` | 1–4, 6, 7, 9 (and many future state layers) | GDAL ESRIJSON driver on `…/query?where=1=1&outFields=*&f=json`; GDAL pages with `resultOffset` automatically. Records the service's `editingInfo.lastEditDate` for freshness. Recipes prefer `arcgis_item_download` (FGDB/shapefile export) when a feature count is above ~200k |
| `http_file` (exists today) | 5, 10, 12 | Plus `where:` (e.g. `t_state = 'ME'`) and GDB layer selection |
| `duckdb_parquet` | 11 | DuckDB spatial: `read_parquet('s3://overturemaps-us-west-2/release/<rel>/theme=buildings/type=building/*', hive_partitioning=1) WHERE bbox.xmin < … AND …` → GeoPackage → existing vector import. Pin the release in the recipe |
| `lfps_job` | 14 | POST job (layer list, AOI = Maine outline, projection 5070 → reproject later) → poll → download zip. Async, so it belongs in the worker |
| `laads_download` | 15 | Bearer `EARTHDATA_TOKEN`; list tiles for a year → download → HDF5 subdataset → mosaic |
| `bdc_api` | 16 | `username` + `hash_value` headers; list as-of dates → list state files → download CSVs → load table; aggregate to H3 (Python `h3`) and blocks |
| `snodas_daily` | 13 | Download tar → extract `.dat.gz` + header → write ENVI `.hdr` → warp/clip to ME → COG per variable per day |

geotools additions: `duckdb` (+ spatial extension baked in at build), `h3`, pinned. GDAL 3.8 already has HDF5 and ESRIJSON. **Verify** it lacks the Parquet driver, which is why DuckDB is used.

### 4.2 Recipe extensions (on top of v2 in the admin plan)

```yaml
source:
  arcgis_feature: { url: ".../FeatureServer/0", where: "1=1", out_fields: "*", page_size: 2000 }
  # or: arcgis_item_download: { item_id: "…", format: fgdb, layer: E911_NG_Addresses }
  # or: duckdb_parquet: { release: 2026-09-23.1, theme: buildings, type: building, bbox: coverage }
  # or: lfps_job: { layers: [LF2025_EVT, LF2025_FBFM40], aoi: coverage }
  # or: laads_download: { product: VNP46A4, collection: 5200, year: 2025, tiles: [h10v04, h11v04] }
  # or: bdc_api: { as_of: latest, state_fips: "23", technology: all }
  # or: snodas_daily: { variables: [swe, depth], keep_days: 120 }
time: { dimension: date, keep: 120d, partition: part_key }   # daily rasters (SNODAS) and dated tables (BDC)
palette: { from: vat, value_field: VALUE, color_fields: [R, G, B], label_field: EVT_NAME }   # paletted COGs
```

`requires_keys` is explicit on every recipe (VIIRS: `[EARTHDATA_TOKEN]`; FCC: `[FCC_BDC_USERNAME, FCC_BDC_API_TOKEN]`; all others `[]`). Missing keys fail fast; that behaviour already exists.

### 4.3 Categorical rasters (hardiness zones, LANDFIRE EVT/FBFM40)

- Write **paletted COGs** (Byte/UInt16 + GDAL colour table built from the VAT or a fixed palette). rio-tiler/titiler applies a dataset's internal colormap automatically, so tile URLs need no giant `colormap=` parameter.
- The class table goes into PostGIS (e.g. `src_landfire.evt_classes(value, name, lifeform, r, g, b)`) for legends and click popups (the point query returns the value; the frontend looks up the name). The legend is generated from the class table (Phase 3 `/stats`-style endpoint, or a static `projects/.../legend.json` built by the recipe).

### 4.4 Time-series rasters (SNODAS daily)

- Parts = dates (`part_key = 2026-02-15`). Freshness = "is yesterday's file there?". Retention keeps N days plus optionally the 1st and 15th of each month for a season archive.
- COG per variable per day: `data/cog/maine/snodas/swe/2026-02-15.tif` (~0.1 MB).
- Frontend: extend `raster-cog` with `{ cog: "maine/snodas/swe/{date}", dates: "/api/…/parts" }` and a date slider control (like today's `controls`). The date list comes from the registry parts (a small public JSON exported per project, since `/api/admin` is private).
- Later option: a titiler **mosaic/time** endpoint. Not needed at this size.

### 4.5 Large vectors (tiles stay fast)

| Dataset | Features | Strategy |
|---|---|---|
| E911 addresses | 792k points | `minzoom 13`; low zooms show a hex-bin count view (`ST_HexagonGrid` materialized) |
| E911 roads | 155k lines | Low zooms: only major road classes (filter on the NG911 road class field), subdivided; full detail from z11 |
| NWI | est. several hundred thousand polygons | Subdivide + generalized dissolve by wetland system for z6–10 (same pattern as soils) |
| Overture buildings | ~1 M polygons | `minzoom 13` only; place categories filtered by zoom |

Target: tiPG tiles under 10,000 features and p95 under 300 ms (checked in `make verify` per dataset).

### 4.6 Schemas, projects, CRS

- **Migration:** `ensure_src_schema` for `src_e911`, `src_dmr`, `src_nwi`, `src_attains`, `src_bpl`, `src_energy`, `src_overture`, `src_climate`, `src_landfire`, `src_fcc`.
- **CRS:** vectors stored in 4326 (convention). Rasters stored as COGs in **EPSG:26919** (LANDFIRE and NWI arrive in 5070 Albers and are warped once). Titiler/tiPG handle Web Mercator.

**Projects** (hub cards, all tagged `maine`):

| Project | Contents |
|---|---|
| `maine-infrastructure` | E911 roads + addresses, wind turbines, broadband availability (H3), night lights |
| `maine-coast` | Shellfish growing areas + classifications, aquaculture leases/LPA, boat launches |
| `maine-water` | NWI wetlands, ATTAINS impaired waters, boat launches (links `hydrology-sketch`) |
| `maine-recreation` | BPL public lands and properties, trails, boat launches |
| `maine-land-cover` | LANDFIRE EVT + fuels, hardiness zones, SNODAS (date slider), NDVI (from the Maine plan) |
| `maine-buildings` | Overture buildings + places |

### 4.7 Registry / dashboard (admin plan)

- New freshness methods:
  - `arcgis_item`: layer `editingInfo.lastEditDate` or item `modified`
  - `overture_release`: STAC `latest`
  - `lfps_version`: newest LF release offered
  - `laads_year`: new annual file
  - `bdc_as_of`: new as-of date
  - `snodas_daily`: yesterday present
- **Outputs:** `cog` + `tile_url` outputs registered with health (Dashboard Phase D). Tile checks go through `/raster/…` from geotools (proxy reachable) or directly to `titiler:8000` on the api network.
- **Keys:** `EARTHDATA_TOKEN` is already listed; add `FCC_BDC_USERNAME`, `FCC_BDC_API_TOKEN` and `EPA_ATTAINS_API_KEY` to `KNOWN_KEYS` and `.env.example` (empty).

## 5. Phasing (each phase: recipes + seeds + project manifest + `make verify` checks + e2e screenshot)

| Phase | Scope | Adapter work | Checks (examples) |
|---|---|---|---|
| **E1: state vectors** | E911 roads + addresses, DMR growing areas + classifications, aquaculture leases/LPA, BPL lands, boat launches | `arcgis_feature` (+ FGDB bundle for addresses), `arcgis_item` freshness | Row counts match the service `returnCountOnly` (155,257 / 792,091 / 447 / 201 / 2,038 / 578 ± edits); z13 address tile < 10k features; NSSP classes within the allowed domain (Approved / Conditionally Approved / Restricted / Conditionally Restricted / Prohibited) |
| **E2: federal vector files** | NWI, US Wind Turbine DB (ME), hardiness zones (vector), ATTAINS GIS layers | `where:` filter, GDB layers, NWI generalization | USWTDB count = API count (466 today); NWI polygon count vs GDB; ATTAINS units all `state = 'ME'`; generalized NWI z7 tile < 10k |
| **E3: Overture** | Buildings + places for Maine | `duckdb_parquet` | Release recorded as vintage; building count within ±5 % of a DuckDB `COUNT` over the bbox; ODbL attribution present on layers |
| **E4: static categorical rasters** | Hardiness grid, LANDFIRE EVT + FBFM40 | paletted COGs, `lfps_job` (worker), class tables | COG valid, EPSG:26919, colour table present; titiler tile 200; point over a known forest returns an EVT code whose class name is found |
| **E5: SNODAS time series** | Daily SWE + depth for Maine, rolling 120 days | `snodas_daily`, time parts, date slider | Yesterday's part present; values within physical ranges (depth 0–5 m); retention prunes old days |
| **E6: keyed sources** | VIIRS Black Marble annual; FCC BDC fixed availability → H3/blocks | `laads_download`, `bdc_api`, `h3` | Fail fast without keys (already enforced); VIIRS radiance non-negative with a lit Portland/Bangor; share of BDC locations with ≥100/20 Mbps per hex in [0, 1]; H3 cells cover Maine |

**Order and dependencies:** E1 and E2 can run from the CLI today. E3–E6 benefit from **Dashboard Phase B** (worker, retries, long jobs, schedules): LFPS jobs are asynchronous, SNODAS is daily, and NWI/Overture are large. Recommended sequence: Dashboard B → E1 → E2 → E4 → E3 → E5 → E6.

## 6. Decisions needed

1. **Trails source:** there's no statewide BPL trails service in the state org. Options: (a) ask DACF/BPL for their trail dataset or an ArcGIS item; (b) Maine Trail Finder data (check terms); (c) OSM paths via Overture `transportation` (ODbL). Recommendation: (a) first, (c) as fallback.
2. **E911 source:** the FGDB bundle (recommended; one download, consistent snapshot) vs paging the feature services (792k addresses = ~400 requests). **Confirm E911 redistribution terms** before publishing addresses publicly on the map.
3. **Shellfish:** hosted classifications stop at 2022. Confirm with DMR whether a current classification layer exists. The map must carry a disclaimer that **classifications are not real-time open/closed status** (closures are issued daily by DMR).
4. **VIIRS source:** Black Marble VNP46A4 with an Earthdata token (recommended; `EARTHDATA_TOKEN` already has a slot) vs EOG VNL (separate account).
5. **FCC display unit:** H3 res-8 hexagons (recommended; no licensed coordinates needed) vs census blocks.
6. **Keys to create when you reach those phases:** NASA Earthdata token (VIIRS), FCC BDC username + API token (broadband), optionally an EPA ATTAINS API key (per-cause detail beyond the GIS layers).

## 7. Risks

| Risk | Mitigation |
|---|---|
| ArcGIS paging limits and timeouts (2,000 per page; 792k addresses) | Prefer FGDB/item exports above ~200k; retries with backoff (worker); count check vs `returnCountOnly` |
| Data-use terms (E911 addresses, Maine Trail Finder, Overture ODbL share-alike) | Recipes carry `license`/`attribution`; verify terms before a public deployment; attribution shown on every layer |
| Misreading shellfish classifications as safety status | Layer description and legend disclaimer; link to DMR closure notices |
| NWI and Overture volume | Generalized views; `minzoom`; disk budget in the dashboard |
| Overture schema changes monthly | Pin `release` per recipe; freshness flags new releases; the upgrade is a deliberate recipe edit |
| LFPS job queue delays and AOI limits | Async job in the worker; poll with backoff; cache the downloaded zip |
| SNODAS format quirks (headers, byte order, no-data −9999) and daily volume | Header parsing tested per variable; retention window; clip to Maine immediately |
| Earthdata tokens expire (~60 days); FCC credentials | Key status page shows last successful use; the fail-fast message names the key |
| FCC location fabric is licensed | Publish only aggregates (H3/blocks); never point locations |
| Disk growth | Estimated total for all of the above, Maine only: **~3–6 GB** (NWI, Overture and SNODAS history dominate); retention settings per recipe |

## 8. Progress log

**2026-09-30: E1 + E2 vectors loaded** (CLI, recorded in `/admin`; `make verify` + e2e green)

| Recipe | Rows | Notes |
|---|---|---|
| me_e911_roads / me_e911_addresses | 155,677 / 798,422 | From the E911 FGDB bundle (222 MB, `NG_ROADS`, `NG_ADDRESSES`); freshness via the ArcGIS item's `modified` time |
| me_dmr_growing_areas / me_dmr_nssp_2022 | 45 / 447 | NSSP: 29 invalid polygons repaired |
| me_dmr_aquaculture_leases / me_dmr_lpa_sites | 201 / 1,315 | |
| me_bpl_lands / me_boat_launches | 2,038 / 578 | |
| attains_me_lines / attains_me_areas | 389 / 421 | EPA server needs small pages (20 / 100); no edit date published, so freshness stays unknown |
| nwi_me | 587,644 | 550 MB GDB, 109 s; 215 invalid polygons repaired; ~970 MB in PostGIS |
| uswtdb_me | 466 | Blank shapefile dates (`0000/00/00`) loaded as text |
| phzm_2023_zones_me | 9 | Vector half-zones; the raster grid waits for E4 |

Importer additions: `source.arcgis {url, where, page_size, params}` (snapshotted to GeoPackage first, because streaming ESRIJSON corrupts dates on COPY), `source.filename`, `source.inner` (a path inside an archive), `where`, `spat`, `ogr_args`, and freshness methods `arcgis_item` (layer last-edit) plus portal-item markers.

**2026-09-30, E4 first raster:** `phzm_2023_grid_me` (`kind: raster`) produces `data/cog/maine/phzm_2023_min_temp.tif`:
412×628 Float32, EPSG:26919, 800 m, values −34.7 to 2.5 °F, 655 KB. The file is swapped in atomically with `.versions/`
retention and a provenance sidecar. Outputs `cog` and `tile_url` are health-checked. It is shown on maine-lands as a `raster-cog`
layer, and clicking reads the value through TiTiler. Checked by e2e and `make verify`.

Not done yet: pub views and project manifests for these datasets (E911 and NSSP need the licensing and disclaimer decisions in §6); trails; E3-E6.
