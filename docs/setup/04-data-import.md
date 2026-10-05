# 04: Data import (GDAL / ogr2ogr)

Data is loaded **by hand, by the operator**. App users don't upload anything.
All GDAL work runs in the **geotools** container (GDAL CLI + R + Python on one GDAL/PROJ build), so nothing is installed on WSL.

## The workflow

```
data/incoming/<file>  →  make inspect  →  make import  →  make datasets  →  pub view (db/seed or projects/)  →  make seed / refresh
                           (look)          (load src_*)    (provenance)       (publish)
```

1. **Put the file in `data/incoming/`.** It's gitignored and mounted read-only in geotools at `/data`. Zips can stay zipped.
2. **Inspect it:**
   ```bash
   make inspect f=parcels.gpkg
   ```
   This shows the driver, layers, feature counts, geometry type, CRS, extent, and fields. If the CRS reads "(none …)",
   you'll need `src_srs=` below.
3. **Import it into a `src_*` schema:**
   ```bash
   make import f=parcels.gpkg t=src_ne.parcels
   ```
   It prints the exact `ogr2ogr` command it runs, then row count, geometry type, SRID, and any invalid geometries.
4. **Check provenance:** `make datasets`.
5. **Publish** by writing a view in `pub` (see "Publishing" below). Until then, the table isn't served anywhere.

## What `make import` does

It runs `scripts/geoimport.py`, which wraps this command:

```
ogr2ogr -f PostgreSQL -nln <schema>.<table>
  -t_srs EPSG:4326 -nlt PROMOTE_TO_MULTI                  # points stay points
  -lco GEOMETRY_NAME=geom -lco FID=id -lco SPATIAL_INDEX=GIST -lco PRECISION=NO -lco LAUNDER=YES
  --config PG_USE_COPY YES -gt 65536 -progress -overwrite
  PG:service=loader  <file>  <layer>
```

Then it runs `ANALYZE`, counts invalid geometries (and fixes them with `fix=1`), and upserts one row into `app.datasets`
with the source path/URL, SHA-256, source and target CRS, geometry type, row count, recipe, license, and notes.

Rules it enforces:
- Targets must be `src_<domain>.<table>` (lowercase). It refuses `pub`, `app`, or anything else.
- The schema must already exist. New domains are created with a migration (below).
- Column names are laundered to lowercase SQL-safe names.

### Options

| Option | Default | Meaning |
|---|---|---|
| `f=` | required | File in `data/incoming/` (or a repo-relative path) |
| `t=` | required | `src_<domain>.<table>` |
| `l=` | only layer | Source layer, for multi-layer files (GeoPackage, FileGDB, KML) |
| `srs=` | `EPSG:4326` | Target CRS. `srs=native` keeps the source CRS |
| `src_srs=` | from file | Source CRS when the file has none or it's wrong (`src_srs=EPSG:26918`) |
| `m=` | `overwrite` | `m=append` adds rows to an existing table |
| `fix=1` | off | Repair invalid geometries with `ST_MakeValid` |
| `clip=1` | off | Clip to ±85.0511° latitude. **Needed for global polygon data that reaches the poles** (e.g. Antarctica), which otherwise makes tiles fail with "tolerance condition error". Recipe key: `clip_web_mercator: true` |
| `oo="K=V K2=V2"` | – | GDAL open options (space-separated) |
| `license=`, `notes=` | – | Stored in `app.datasets` |

## Formats

| Format | Example |
|---|---|
| GeoPackage | `make import f=roads.gpkg l=roads t=src_trans.roads` |
| Shapefile (zipped) | `make import f=parcels.zip t=src_cad.parcels` (read via `/vsizip/`, no unzip needed) |
| Shapefile (loose) | Put all sidecar files (`.shp .shx .dbf .prj`) in `data/incoming/`, then `f=parcels.shp` |
| GeoJSON | `make import f=sites.geojson t=src_ne.sites` |
| File Geodatabase | `make inspect f=county.gdb` then `make import f=county.gdb l=Parcels t=src_cad.parcels` |
| CSV with lon/lat | `make import f=gauges.csv t=src_hydro.gauges`. Columns named `lon*`/`long*`/`x` and `lat*`/`y` are detected, types are auto-detected, and the CRS defaults to EPSG:4326 |
| CSV, other column names | `oo="X_POSSIBLE_NAMES=easting Y_POSSIBLE_NAMES=northing" src_srs=EPSG:27700` |
| KML / KMZ | `make import f=trail.kml l=<layer> t=src_rec.trails` |

## CRS guidance

- **Store EPSG:4326 by default.** tiPG and MapLibre handle it natively, and the whole stack assumes it.
- Keep a projected CRS (`srs=native`) only when you'll do area or distance analysis in SQL on that table.
  Then either publish with `ST_Transform(geom, 4326)` in the view, or transform in the analysis.
- If a file has no `.prj` or the CRS is wrong, set `src_srs=` explicitly. `app.datasets.source_srs` records what was used.

## Recipes: imports that survive resets

An ad hoc `make import` prints a **recipe stub** at the end. Save it as `data/recipes/<name>.yaml` (committed) to make
the import reproducible:

```yaml
name: county_parcels            # must equal the file name
description: County parcels 2026
source:
  path: county_parcels_2026.zip # in data/incoming/   (or  url: https://...  to download into data/cache/downloads/)
  layer: parcels                # optional
target: src_cad.parcels
srs: EPSG:4326
mode: overwrite
fix_invalid: true               # optional
open_options: []                # optional
license: County open data, CC-BY 4.0
notes: Downloaded 2026-09-29 from the county portal
enabled: true                   # false = listed as a todo and skipped by import-all
todo: null                      # shown when disabled
```

```bash
make import-recipe r=county_parcels
make import-all                          # every enabled recipe, alphabetical; failures are summarized at the end
```

`make reset-db` rebuilds data **only** from recipes. Anything imported without one is listed and lost.

## Re-importing an existing table

- **No views depend on it:** plain overwrite (drop and recreate).
- **`pub` views depend on it:** ogr2ogr would `DROP … CASCADE` those views, so geoimport loads into
  `src_x._stage_<table>` instead, then swaps the rows in place inside one transaction. The views stay.
  If the new data has **different columns**, it stops and tells you which. Then drop the views (`make psql`),
  re-import, and run `make seed`.

## Deleting a dataset

```sql
-- make psql
DROP TABLE src_cad.parcels;                -- add CASCADE only if you mean to drop dependent views too
DELETE FROM app.datasets WHERE table_schema = 'src_cad' AND table_name = 'parcels';
```
Also remove or disable its recipe.

## A new source domain (schema)

```bash
make migration n=src_cad
# edit the new file under -- migrate:up:
#   CALL app.ensure_src_schema('src_cad');
make migrate
```
`ensure_src_schema` creates the schema and grants the loader and readers exactly what they need.

## Publishing: make a table visible to tiPG

tiPG only serves the `pub` schema. Publish with a view named `pub.<project_slug>__<layer_id>`:

```sql
CREATE OR REPLACE VIEW pub.flood_risk__parcels AS
SELECT id, parcel_id, zone, area_m2, geom      -- only the columns the map needs
FROM src_cad.parcels;
```

- Needs an `id` column (unique) and a single `geom` column with a declared SRID. Imports already provide both.
- For now, put placeholder-project views in `db/seed/*.sql` and run `make seed`. Phase 3 moves project views to
  `projects/<slug>/sql/` with `mapgen apply`.
- Run `make refresh`, then check http://localhost:8080/tiles/collections.
- Parametrized layers use SQL functions `pub.<slug>__<name>(z int, x int, y int, <params>)` returning the tile's
  features (no project uses one at the moment; the Hydrology Sketch example was removed on 2026-10-05, see git history).
  They must be `SECURITY DEFINER` with a fixed `search_path`, because tiPG's role can't read `src_*`.

## Rasters

Rasters aren't stored in PostGIS. They become Cloud Optimized GeoTIFFs in `data/cog/`, which TiTiler serves at
`/raster/<name>/{z}/{x}/{y}.png` (plus `/point/<lon>,<lat>` and `/info`).

**Raster recipes** (repeatable; the example is `data/recipes/phzm_2023_grid_me.yaml`):

```yaml
kind: raster
source: { url: https://…/grid.zip, inner: grid.bil }   # or path:
target: cog:maine/phzm_2023_min_temp                     # -> data/cog/maine/phzm_2023_min_temp.tif
srs: EPSG:26919
resolution: 800            # metres (target CRS units)
resampling: bilinear       # nearest for categorical rasters
spat: [-71.1, 42.95, -66.9, 47.47]   # lon/lat clip
nodata: -9999
retention: { keep_versions: 1 }
```

`make import-recipe r=<name>` warps and writes a COG (DEFLATE, 512 px blocks, internal overviews). It checks that the layout
is COG and that there are valid pixels, then swaps the file in atomically. The previous file moves to
`data/cog/.versions/<name>/`, and a provenance sidecar `<name>.json` (source checksum, parameters, stats) is written next to it.
The COG and its tile URL are registered in the admin dashboard and health-checked. COGs live on disk, so `make reset-db` does not
touch them, and `make import-all` skips raster recipes unless you pass `rasters=1`.

### More source types

| `source:` | What it does | Example recipe |
|---|---|---|
| `tiles: {template, north: [a, b], west: [c, d]}` | A grid of remote COG tiles (`{tile}` = `n44w070`): the tiles that exist become a VRT read over HTTP | `me_terrain_dem_30m` (USGS 3DEP) |
| `derive: {from: <cog>, gdaldem: [hillshade, …]}` | A raster made from another COG with `gdaldem` (hillshade, slope, aspect, …) | `me_terrain_hillshade`, `me_terrain_slope` |
| `derive: {from: <cog>, contour: {interval, attribute}}` | Contour lines from a COG (`gdal_contour`), imported as a vector table | `me_terrain_contours_100ft` |
| `overture: {release, theme, type, columns, where, clip_sql}` | Overture Maps GeoParquet read from S3 with DuckDB, only for the area of `clip_sql` (`release: latest` uses the newest) | `me_overture_buildings`, `me_overture_places` |
| `landfire: {layer, resolution, projection}` | A LANDFIRE layer through the LANDFIRE Product Service (an asynchronous job; needs `LANDFIRE_EMAIL`). New versions roll out by region: an unreleased region returns only nodata, so the import stops with a message; use the previous version (LF2024 for Maine as of October 2026) | `me_landfire_evt`, `me_landfire_fbfm40` |
| `census_api: {dataset, get, for, in, geoid}` | A Census Data API table (`kind: table`; needs `CENSUS_API_KEY`) | `me_acs5_2024_tract` |
| `ssurgo: {areas: "ME%", layer: soilmu_a}` | SSURGO soil polygons from Web Soil Survey, one zip per survey area (cached per save date, so a refresh only fetches re-published areas), merged into one table; freshness `sda_sacatalog` compares each area's save date | `me_ssurgo_mupolygon` |
| `sda: {query, key, text_columns}` | A USDA Soil Data Access SQL query as a table (`kind: table`; no key). Columns of all numbers become numeric unless listed in `text_columns` | `me_ssurgo_mapunit` |
| `geoparquet: {url, s3_url_style, columns, where, clip_sql}` | Any GeoParquet with a `bbox` column on S3, read with DuckDB and clipped to `clip_sql` (Overture uses the same code). `s3_url_style: path` for buckets with dots in the name | `me_hifld_hospitals` (HIFLD archive on Source Cooperative) |
| `url` + `inner` + `stream: true` (raster) | Read a remote COG, optionally inside a zip stored without compression, with HTTP range requests: only the blocks inside the cutline are fetched | `me_nlcd_2025_landcover` (1.5 GB national zip, about 40 MB read) |
| `cdl: {year, fips}` | USDA NASS Cropland Data Layer for one state from CropScape (keeps NASS's colour table) | `me_cdl_2025` |
| `rasterize: {sql, attribute, type}` | Burn PostGIS polygons into a categorical COG (overviews use nearest, so classes never blend) | `me_ssurgo_hsg_30m` |

Raster recipes also take:
- `cutline_sql`: an SQL query returning the polygon to clip to (e.g. Maine's towns), run against PostGIS.
- `class_stats: true` (categorical rasters): after the COG is built, the acres of each class in each Maine county are
  written to `src_raster.class_area`, which projects publish as views for charts (rasters are files, so charts cannot
  read them directly; see `projects/maine-landcover/sql/010_class_area.sql`). Rerun for an existing COG with
  `docker compose run --rm geotools python scripts/geoimport.py class-stats <recipe>`.
- `cog_options`: extra COG creation options, e.g. `[PREDICTOR=YES]` for elevation.

`depends_on: [recipe, …]` orders `make import-all`, so derived layers are built after their source.

One-off conversion without a recipe:

```bash
make cog f=dem.tif          # -> data/cog/dem.tif (DEFLATE, internal overviews)
```
In-database rasters (`raster2pgsql`, available in geotools) are an escape hatch for SQL raster analysis only.

## Large files (rare, manual)

- Imports use `PG_USE_COPY` and 65,536-row transactions already.
- For very large sources, import into a separate table and then `INSERT … SELECT` into the target in SQL,
  or split the source by extent or attribute with `-where` / `-spat` in a manual `ogr2ogr` via `make tools-sh`.

## Using the data from R and Python

`make r` and `make py` open sessions in geotools connected as **analyst_ro** (read-only):

```r
con <- DBI::dbConnect(RPostgres::Postgres())                        # service=analyst via PGSERVICE
x <- sf::st_read(con, query = "SELECT * FROM src_ne.countries")
```

```python
import psycopg, geopandas as gpd, sqlalchemy
eng = sqlalchemy.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect("service=analyst"))
gdf = gpd.read_postgis("SELECT * FROM src_ne.countries", eng, geom_col="geom")
```

Scripts in `analysis/` are available at `/work/analysis` inside geotools:
`make tools-sh`, then `Rscript analysis/foo.R` or `python analysis/foo.py`.

### Notes on specific sources

- **HIFLD**: DHS retired HIFLD Open on 2025-08-26. The `me_hifld_*` recipes read the final snapshot archived on
  Source Cooperative (`seerai/hifld`); they will not change, so their freshness method is `none`.
- **EIA Energy Atlas** layers are hosted by the federal GeoPlatform (`services2.arcgis.com/FiaPA4ga0iQKduv3`). Some
  of its services key on `FID` rather than `OBJECTID`: set `order_by: FID` or paging fails.
- **Broadband**: the Maine Connectivity Authority's own map server (`gis.cgs.earth`) did not respond in October 2026,
  so `me_broadband_fcc_*` load the FCC Broadband Data Collection (December 2025) aggregated by Esri PolicyMap.
- **NAIP** is not downloaded (statewide 60 cm imagery is around a terabyte); it is a basemap (`naip`, `naip-labels`)
  served live by The National Map's image service.
- **3DEP lidar**: `me_terrain_dem_10m` is the 1/3 arc-second DEM (lidar-derived across Maine); `me_3dep_lidar_projects`
  (WESM) shows each lidar collection's footprint, dates, quality level and links to the 1 m DEM and point clouds.
- **Sensitive locations**: the MDIFW Essential Habitat recipes use MDIFW's published habitat polygons, not the
  nest-site points some services also expose.
