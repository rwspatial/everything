# 07 · Projects: create, validate, publish (Phase 3)

A project is one map: a manifest (`projects/<slug>/project.json`) listing its layers, plus the SQL for the
`pub` views those layers draw. There are two ways to make one, and both write the same manifest and run the
same checks:

| | Command line (`./mapgen`) | Browser (`/admin/new`) |
|---|---|---|
| Best for | anything, including custom SQL and several layers | one layer on an existing `pub` view |
| Writes | `projects/<slug>/` files, then the registry | the registry, then `./mapgen export` writes the files |
| Login | none (runs in your shell) | admin login (`make admin-credentials`) |

The hub and the viewer read the **project registry** (`app.projects`, served by core-api at `/api/projects`).
If core-api is down they fall back to the static files in `projects/`, so maps keep working.

## Walkthrough: Maine towns by median household income

This is how `maine-overview` was made.

1. **Load the data** (recipes are in `data/recipes/`):

   ```bash
   make import-recipe r=me_cousub              # TIGER/Line 2024 county subdivisions -> src_census.cousub
   make import-recipe r=me_acs5_2024_cousub    # ACS 5-year via the Census API (needs CENSUS_API_KEY in .env)
   ```

2. **Scaffold the project**:

   ```bash
   ./mapgen new maine-overview --title "Maine Overview" --layer towns \
     --layer-title "Median household income by town" --from src_census.cousub
   ```

   That writes `projects/maine-overview/project.json`, `projects/maine-overview/sql/010_towns.sql`, and
   adds the slug to `projects/index.json`. New projects open on Maine.

3. **Write the view** in `sql/010_towns.sql` (keep `CREATE OR REPLACE`; `DROP VIEW` first if you remove or retype
   columns). tiPG needs an `id` column and exactly one geometry column with a declared SRID:

   ```sql
   CREATE OR REPLACE VIEW pub.maine_overview__towns AS
   SELECT c.id, c.geoid, c.name, c.namelsad, split_part(a.name, ', ', 2) AS county,
          a.pop::integer AS pop, a.median_hh_income::integer AS median_hh_income,
          a.median_hh_income_moe::integer AS median_hh_income_moe, c.geom
   FROM src_census.cousub c LEFT JOIN src_census.acs5_2024_cousub a USING (geoid);
   ```

4. **Style the layer** in `project.json` (a `step` expression on `median_hh_income`, a legend, a popup
   template such as `{namelsad}, {county}: median household income ${median_hh_income} (±{median_hh_income_moe})`).
   The wizard's statistics endpoint gives quantile breaks; from the command line:
   `SELECT percentile_disc(array[0.2,0.4,0.6,0.8]) WITHIN GROUP (ORDER BY median_hh_income) FROM src_census.acs5_2024_cousub;`

5. **Publish**:

   ```bash
   ./mapgen apply maine-overview
   ```

   It runs four steps and stops at the first failure:
   1. Validates the schema, rules and MapLibre style spec (offline).
   2. Runs `projects/<slug>/sql/*.sql` through the migrator, so the view is owned by the database owner and tiPG's
      grants apply.
   3. Restarts tiPG so it sees the view.
   4. Validates against the live database, then registers the project.

   Then open `http://localhost:8080/p/maine-overview`.

## The wizard (`/admin/new`)

1. Pick a published view (any `pub` view tiPG serves).
2. Pick a preset:
   - single colour
   - categories (the 10 most common values)
   - classed colours (quantiles computed in PostGIS)
   - circles sized by a number (points)
   - heatmap (points)
3. Name the project and check the live preview.
4. **Validate** shows the same report as `./mapgen validate`. **Save** registers the project. To keep it in git:

   ```bash
   ./mapgen export <slug>     # writes projects/<slug>/project.json, byte-identical to what was saved
   ```

A project saved in the wizard and not yet exported is protected: `./mapgen sync` will not overwrite it. Projects
saved in the wizard can be deleted through `DELETE /api/admin/projects/<slug>`. File-managed projects cannot be deleted
there; remove them from `projects/index.json` instead.

## Commands

| Command | What it does |
|---|---|
| `./mapgen new <slug> [--template T] [--title …] [--layer id] [--from src_x.table]` | Scaffold from a template (`blank`, `vector-basic`, `hydro`, `analysis`; see `templates/projects/README.md`) |
| `./mapgen validate <slug> [--offline] [--json]` | All checks, plus the MapLibre style spec |
| `./mapgen apply <slug>` | Validate, run the SQL, refresh tiPG, register |
| `./mapgen sync [--check]` | Register every project in `projects/index.json` (also run by `make bootstrap` and `make reset-db`); `--check` only reports drift |
| `./mapgen export <slug> [--stdout]` | Registry → file (for wizard projects) |
| `./mapgen list` | What is registered, its version, and whether it is valid |
| `./mapgen check-templates` | The placeholder projects must be reproducible from their templates |
| `./mapgen import …` | Alias for `scripts/geoimport.py` |
| `make contracts` / `make contracts-check` | Regenerate / check the frontend types after editing the schema |
| `make validate-styles [p=<slug>]`, `make projects-sync`, `make projects-check` | The same checks as make targets |

## Validation codes

Errors (`E_*`) block `apply` and saving; warnings (`W_*`) don't.

| Code | Meaning | Fix |
|---|---|---|
| `E_SCHEMA` | The manifest breaks `contracts/project-manifest.v1.schema.json` (the path says where) | Edit the manifest |
| `E_SOURCE_TYPE` | Unknown `source.type` | Use one of `tipg-vector`, `tipg-geojson`, `geojson-url`, `raster-xyz`, `raster-cog` |
| `E_SLUG_MISMATCH` | The `slug` differs from the folder or URL | Make them match |
| `E_DUP_LAYER` | Two layers share an id | Rename one |
| `E_READY_TODO` | A `ready` project still has to-do layers | Finish them or set the status to `draft` |
| `E_NO_LAYERS` | A `draft` or `ready` project has nothing to draw | Add a layer or set the status to `stub` |
| `E_ZOOM_RANGE`, `E_CONTROL_PARAM` | `minzoom` > `maxzoom`; a slider without a default in `source.params` | Edit the layer |
| `E_VIEW_MISSING` | The collection is not in `pub` | Run the SQL (`./mapgen apply`), then refresh |
| `E_NOT_SERVED` | The view exists but `tipg_ro` cannot read it | Create `pub` objects through the migrator (`./mapgen apply`, `make seed`), not by hand |
| `E_NO_GEOM`, `E_MULTI_GEOM` | No geometry column, or more than one | Publish exactly one |
| `E_SRID` | The geometry column has no declared SRID | Cast it: `geom::geometry(MultiPolygon, 4326)` |
| `E_NO_ID` | No `id` column | Select one (tiPG uses it as the feature id) |
| `E_PARAM_UNKNOWN` | `source.params` names an argument the function doesn't have | Fix the name |
| `E_PROPERTY_UNKNOWN` | `source.properties` lists a missing column | Fix the name |
| `E_COG_MISSING` | `data/cog/<name>.tif` is missing, or TiTiler can't open it | Build it (`make import-recipe r=…`) |
| `E_STYLE` | A style fragment breaks the MapLibre style spec | Edit the style (the message names the property) |
| `W_NO_GIST` | The table behind the view has no GiST index | `CREATE INDEX ON src_x.t USING gist (geom)` |
| `W_GEOJSON_ROWS` | A `tipg-geojson` layer has more than 5,000 rows | Use `tipg-vector` |
| `W_TEMPLATE_FIELD`, `W_STYLE_FIELD` | A popup or style reads a column the view doesn't have | Fix the field name |
| `W_PROPERTY_FILTERED` | The popup or style uses a column missing from `source.properties`, so tiles omit it | Add it to `properties` |
| `W_TODO_REASON`, `W_NO_STYLE`, `W_CONTROL_RANGE` | A to-do layer without a reason; a vector layer without a style; a slider default outside its range | Edit the layer |

## Changing the contract

Edit `contracts/project-manifest.v1.schema.json`, then run `make contracts`, which regenerates
`frontend/src/lib/contracts.gen.ts`. Then rebuild core-api, which bakes in the schema and `validate.py`:
`docker compose up -d --build core-api`. `make verify` fails if the generated types are stale.
