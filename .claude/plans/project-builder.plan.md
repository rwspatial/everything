# Project Builder (unit-first project creator) — Plan

Status: **confirmed 2026-10-03; Stage 1 in progress**
Replaces: the single-view wizard at `/admin/new` (`frontend/src/routes/admin/new/+page.svelte`).
Builds on: `spatial-app-architecture.plan.md` Phase 5 (analysis workers, `app.processes`, `app.publish_job_layer`),
`admin-dashboard.plan.md` (dataset registry, job queue).

## Verified today

| Fact | Evidence |
|---|---|
| The creator today = 1 published view → 1 styled layer (5 presets) → manifest | `admin/new/+page.svelte`, `lib/presets.ts` |
| Analyses exist but live on a separate page and only output a vector layer + JSON report | `admin/analysis`, `contracts/process.v1.schema.json` (`outputs.layer` is required, `const: vector-layer`) |
| 2 processes: `py.getis_ord_hotspots`, `r.local_moran` | `workers/processes/` |
| Candidate units already loaded (rows): parcels 708,382 + 36,282 · census block 47,138 · block group 1,184 · tract 407 · town/cousub 529 · county 16 · state (NE admin1) | `geometry_columns`, `app.dataset_outputs` |
| ACS 2024 5-year attributes exist for block group, tract, cousub, county; Decennial 2020 for blocks | `src_census.acs5_2024_*`, `dec2020_block` |
| Overlay sources available for per-unit extraction: flood zones (145k), wetlands (589k), conserved lands, habitat (10 layers), soils (403k), broadband, roads, DEM/slope COGs, land cover | `src_*`, `data/cog/` |
| Worker image: scikit-learn, esda, libpysal, geopandas, R sf/spdep/terra/rmarkdown, **Quarto + pandoc**. Missing: matplotlib, spopt, exactextract(r), ranger | checked in `worker` container |
| No D3 in the frontend yet | `frontend/package.json` |

---

## 1. The model

A project is built around **one primary unit** and a **study area**. Everything else attaches to that unit.

```
Project
 ├─ unit:        tract                     (what every row/polygon is)
 ├─ study area:  Cumberland + York counties (which units; required for parcels and blocks)
 ├─ attributes:  ACS income, population …  (columns joined on the unit's key)
 ├─ context layers: contours, roads, flood zones …   (reference styles, not per-unit)
 ├─ analyses:    each = process + inputs → outputs, run manually, re-runnable
 │     outputs: new unit columns │ map layer │ table │ chart (D3) │ PDF report
 └─ views:       map (unit choropleth + context) · charts panel · reports list
```

### 1.1 Units (catalog: `data/units/*.yaml` → `app.units`, same YAML-is-truth rule as recipes)

| Unit | Source | Key | Parents | Notes |
|---|---|---|---|---|
| Parcel | `src_megis.parcels_*` | id | town → county | Study area **required** (≤ one county or a few towns); minzoom 13 |
| Census block | `src_census.block` | geoid | block group → tract → county | Decennial 2020 counts only; study area required |
| Block group | `src_census.blockgroup` | geoid | tract → county | ACS 2024 |
| Tract | `src_census.tract` | geoid | county | ACS 2024 |
| Town / township | `src_census.cousub` | geoid | county | ACS 2024; MEGIS towns for the coastline-accurate outline |
| County | `src_census.county` | geoid | state | ACS 2024 |
| State | Census states (bootstrap recipe `us_states`) | geoid | – | For multi-state later |

**Not in scope now (noted for later, decided 2026-10-03):** the seven units above are the whole Stage 1–5 set.
Candidates to revisit once the builder is in use:

| Unit | Source | Key | Why it might be worth adding |
|---|---|---|---|
| **Hex grid** (1 / 5 / 25 km²) | Generated in PostGIS (`ST_HexagonGrid`), no download | hex id | Equal-area: the best unit for hot spots and ML, because every cell is the same size. Cheapest to add (no recipe) |
| Watershed (HUC-12 / HUC-10) | USGS WBD (new recipe) | huc12 | Natural unit for water, habitat and land-cover questions |
| ZIP code area (ZCTA) | Census ZCTA5 (new recipe) | zcta5 | Often asked for; does not nest in towns |
| Legislative / school districts | Census SLDU/SLDL/UNSD (new recipes) | geoid | Civic reporting |

The unit catalog (`data/units/*.yaml`) is designed so any of these is one YAML file plus, where needed, one recipe.

Each unit declares: `key`, `name` expression, `parents`, `geometry_table`, `attribute_sets` (e.g. `acs5_2024`), `max_units_without_study_area`, `minzoom`.

### 1.2 Study area
Pick whole Maine, or counties / towns / a drawn box. Stored as a filter on the parent chain (e.g. `county in (23005, 23031)`), so it stays readable and re-runnable.

### 1.3 Context layers (catalog of reusable styled layers)
Not per-unit analyses — just good reference styles: contours, hillshade, roads, rail, hydrography, flood zones, wetlands, conserved lands, parcels outline, town lines, broadband …
**Source of the catalog: the layer specs that already exist in `projects/*/project.json`**, de-duplicated and tagged (`catalog: true` + category), so one curated style is reused everywhere instead of being re-made in the wizard.

### 1.4 Analyses (process catalog, extended)
Run **manually** from the project (button → job → result), re-runnable, inputs remembered in the manifest.

| Family | Example processes | Output |
|---|---|---|
| **Extraction** (overlay a source onto the unit) | % of unit in flood zone / wetland / conserved land · length of roads per km² · count of points (schools, wells, shelters) · raster zonal stats: mean elevation, slope, % land cover class · soils: % hydric, dominant HSG | New unit columns (+ choropleth layer) |
| **Statistics** | Local Moran's I, Gi* (existing), global summaries, correlation matrix, bivariate | Layer + table + charts |
| **ML** | K-means / regionalization (spopt SKATER, max-p) · random-forest prediction of a target from extracted columns · anomaly detection | Layer + model report (feature importance, metrics) |
| **Reports** | Unit profile (one unit, e.g. a town), study-area summary | PDF |

Contract change (`process.v2`): inputs gain `unit-ref` and `columns-ref`; outputs become a list of typed outputs: `unit-columns`, `vector-layer`, `table`, `chart`, `report-pdf`. v1 descriptors keep working (mapped to one `vector-layer`).

### 1.5 Charts (D3)
A small chart contract (`chart.v1`): `histogram | bar | scatter | box | ranked-bar | line`, plus a data reference (unit columns or an analysis table) and encodings. Rendered with D3 in a project **Charts panel**; **linked to the map** (hover/brush a bar → highlight units, click a unit → highlight its mark). Processes can emit chart specs; users can also add a chart on any unit column.

### 1.6 Reports (PDF)
**Quarto → PDF through Typst** (in the image already; no LaTeX). The worker renders a `.qmd` template with the unit data, static maps (matplotlib/geopandas, to be added) and chart images, and stores the PDF under `data/reports/<project>/<job>.pdf`, served by core-api behind the project's access rules. Templates: *study-area summary*, *unit profile*. *(Verify Typst output inside the container in Stage 4.)*

---

## 1.7 Map designs: the quick path (added 2026-10-03 at the user's request)

Most of the time the goal is "a beautiful, informative map of Bethel", not a blank slate. So `/admin/new` opens on
two choices: **Quick map** (place + design, below) and **Build from units** (§2, the full builder).

**Quick map = pick a place, pick a design, get a finished project.**
1. **Place:** one unit row, e.g. a town or township, a county or a tract, from the same `pub.units__*` views (search by name).
2. **Design:** a hard-coded, curated template that fits that geography. Each design is a file,
   `templates/designs/<id>.json`, listing:
   - `geographies`: the units it suits (`["town"]`, `["county"]` …)
   - the layers, in order, with finished styles: referenced from the context-layer catalog (§1.3), and from the unit view
     (the place itself, its neighbours)
   - **focus treatment:** the place outline, plus a soft mask that dims everything outside it. One generic tiPG function,
     `pub.units_mask(unit, key)`, returns "bounding box minus the place", so no per-place SQL is needed
   - framing (fit to the place's bounds plus padding, basemap, pitch for terrain designs), title and subtitle templates
     (`{name}, {county_name} County`), the attribution block, and which popups are on
   - an optional statistics panel, e.g. population, median income, area and conserved acres (Stage 3 charts plug in here)
3. **Result:** a normal manifest saved through the existing projects API (admin only), opened at `/p/<slug>`. "Customize"
   opens it in the full builder.

**First designs** (Maine-first; all layers already loaded):

| Design | Geography | Contents |
|---|---|---|
| **Town atlas** | town | Hillshade, contours (10 m DEM once its contours are built), water and wetlands, conserved lands, roads by class, parcels from z13, town outline with mask, labels |
| **Town hazards & resilience** | town | Flood zones (FEMA), wetlands, steep slopes, roads, shelters and schools, outline and mask |
| **Town natural resources** | town | Beginning with Habitat focus areas, deer wintering, vernal pools, undeveloped blocks, conserved lands, soils (farmland) |
| **County overview** | county | Towns shaded by median income (or population density), roads, water, county mask, town labels |
| **Neighbourhood demographics** | tract, block group | The unit and its neighbours shaded by a chosen ACS measure, roads and labels |

Later: a printable / PDF poster version of each design (shares the Stage 4 report renderer).

## 2. Creator flow (`/admin/new`, rebuilt)

```
1 Unit ─▶ 2 Study area ─▶ 3 Attributes ─▶ 4 Context layers ─▶ 5 Analyses ─▶ 6 Save
  cards     map picker       ACS sets,       catalog with        pick + configure;   manifest +
  (count,   (counties,       choose the      thumbnails;         run now or later    first runs
  nesting)  towns, box)      mapped field    toggle on/off
```
Live preview on the right throughout (existing `Viewer`). After saving, the project page has an **Analyses** drawer (admin only) to run, re-run and inspect results, plus **Charts** and **Reports** tabs.

---

## 3. Data model

- `app.units` (synced from `data/units/*.yaml`).
- Manifest v1.1 (optional keys, old projects unaffected): `unit {id, studyArea}`, `attributes[]`, `analyses[] {id, process, version, inputs, lastJobId, outputs[]}`, `charts[]`, `reports[]`.
- Per-project unit table: `pub.<slug>__units`, a view = unit geometry ⋈ attributes ⋈ extracted columns, filtered to the study area. Extracted columns live in `app.unit_values (project, unit_key, column, value, job_id)` (long format; the view pivots the selected ones), so re-running an analysis replaces only its columns.
- Charts/report artefacts: `app.job_outputs (job_id, kind, path|spec, bytes)`.

---

## 4. Stages (each ends with `make verify` + e2e + screenshots)

| Stage | Scope | Done when |
|---|---|---|
| **1a. Units** (done 2026-10-03) | Migration `app.units` + `src_units` lookups; `db/seed/070_units.sql`: seven `pub.units__*` views with standard columns and the catalog rows (catalog lives in the seed next to its views, not in YAML) | All 7 units listed; every block and all but 40 of 744,664 parcels matched to a town; ACS joins complete |
| **1b. Quick map (designs)** | `/api/admin/units`, place search; context-layer catalog API; `pub.units_mask`; `templates/designs/*.json` (Town atlas + County overview first); `/admin/new` landing with the two paths; quick-map flow | Pick "Bethel" + "Town atlas" → a saved, good-looking project in three clicks; e2e screenshot reviewed |
| **1c. Build from units** | Steps 1–4 + 6 of §2: unit, study area (map filter + bounds), attribute choropleth, context layers, save; manifest gains optional `unit` | Build "Cumberland County tracts, median income, with contours + roads" in the UI in under a minute; old projects unchanged |
| **2. Analyses attached to projects** | `process.v2`; `unit-ref`; `app.unit_values`; extraction processes (vector overlay %, point counts, line density, raster zonal stats via exactextract); existing Moran/Gi* adapted; Analyses drawer (run / re-run / results) | "% of each tract in a flood zone" runs from the project and becomes a mappable column |
| **3. Charts (D3)** (done 2026-10-03: `charts[]` in the manifest schema + validator (`E_CHART_*`), `GET /api/projects/{slug}/charts/{id}[?bbox]`, `lib/charts/` Chart + ChartsPanel, charts in 10 projects and all 5 designs) | `chart.v1`; Charts panel; map ↔ chart linking; process-emitted charts | Histogram + scatter of two columns, brushing highlights tracts |
| **4. Reports (PDF)** (done 2026-10-03, **changed approach**: a printable page `/p/<slug>/report` printed by headless Chromium (`services/reporter`), not Quarto/Typst, so the PDF shows the same map and D3 charts as the site; `app.reports`, admin-only queue, public download) | Quarto/Typst templates; static maps; report jobs; download list | Study-area summary PDF for the Cumberland project, opened and reviewed |
| **5. ML + more units** | k-means / SKATER / max-p (spopt), random forest (scikit-learn) with metrics + feature importance; WBD HUC-12, ZCTA recipes | Regionalize towns by 5 extracted columns; RF model report |

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| Parcels/blocks are large (745k / 47k) | Study area required above a unit-count threshold; extraction processes chunk by parent unit; tiles keep minzoom |
| Overlay extraction is slow on big sources (wetlands 589k, soils 403k) | Pre-subdivided source tables (`ST_Subdivide`), GiST, per-chunk progress, cache results per (unit, source, source version) |
| Scope creep (charts, PDFs, ML all at once) | Strict stage gates; each stage useful on its own |
| Two creators during the transition | Keep the old one at `/admin/new/simple` until Stage 1 ships, then remove |

## 6. Decisions (2026-10-03)

1. Units: **parcel, block, block group, tract, town, county, state only.** Hex grid, HUC-12, ZCTA and districts noted in §1.1 for later.
2. Audience: **admin only.** Building projects, running analyses and generating reports stay behind `/admin` auth, including when hosted publicly. Public visitors only view published maps, charts and reports.
3. Charts: **D3** (linked map–chart interaction).
4. Reports: ~~Quarto + Typst~~ → **print the report page with headless Chromium** (decided while building Stage 4: one rendering path for maps and charts; Typst remains an option for long-form text reports).
5. **Quick map from a design** is the default entry to `/admin/new` and ships first (Stage 1b); the full builder is the second path.

## 7. Follow-ups noted (not part of this plan)
- Maine Terrain still uses the 30 m DEM; the 10 m DEM COG is now built (`data/cog/maine/dem_10m.tif`, 2.6 GB).
  Build `hillshade_10m`, `slope_10m` and 20-ft contours from it, then switch the map and the Town atlas design to them.
