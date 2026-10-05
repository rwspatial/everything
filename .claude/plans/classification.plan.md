# Classification & derived layers — Plan

Status: **§1 built (2026-10-04/05), uncommitted until reviewed.** What shipped differs from the draft below:
- Edits live in the database (`app.settlement_edits`, migration `20261004000100`), not a GeoJSON file in git; the
  in-app editor (`/admin/methods/settlements/edit`, terra-draw) came first. A `make edits-export` to GeoJSON is a
  possible follow-up if git history of edits is wanted. On AWS, edits travel with `make aws-deploy data=1`.
- `src_units.apply_settlement_edits()` writes `src_units.settlements_final` (seconds); core-api calls it after every
  create/update/delete (`/api/admin/settlement-edits`), so no checksum-triggered rebuild is needed.
- Decisions taken (§1.5): replace outlines are used **exactly as drawn**; a partly cut computed settlement keeps its
  remaining parts of **1 acre or more**. Edits can also set a name and a size class (the classification override).
- Map: `source` = computed | edited; edited outlines draw darker and heavier on Maine Places.
- Open: §1.5 item 3 (the same pattern for other classification layers).

**Method v4, Degree of Urbanisation (2026-10-05, the default).** Settlements are classified from a 100 m building
density grid (3x3 window; dense >= 6 buildings/ha or 15 % cover, semi-dense >= 2.5/ha or 6 %), contiguous dense and
semi-dense cells of 50+ buildings forming City / Town / Suburb / Village; the remaining buildings form Hamlets and
Roadside strips (v3 wall-to-wall clustering). Outlines are still drawn from the footprints. Classes replace the old size
classes everywhere (`settlement_class`; edits migration `20261005000200`). Grid published as
`pub.maine_places__density_grid`. Write-up with formulas, parameters and references: `docs/methods/settlements.json`.
Possible follow-ups: calibrate thresholds against Census places/urban areas; residential addresses instead of
buildings as the population proxy.
Covers derived classification layers (computed from source data by a documented method, e.g. settlements) and how
people correct them. Related: `docs/methods/*.json` (method write-ups shown on /admin/methods),
`project-builder.plan.md` (units, analyses).

## Current state (verified 2026-10-03)

| Layer | Method | Where |
|---|---|---|
| Settlements (built-up areas) | Method 3: building footprints clustered wall to wall (DBSCAN 45 m, 4 neighbours), closed (buffer +45 / −35 m), touching shapes dissolved, large buildings within 100 m attached, holes under max(10 acres, 3 % of the settlement) filled, ≥ 10 buildings. 6,205 settlements statewide | `projects/maine-places/sql/030_settlements.sql`, `docs/methods/settlements.json`, `pub.maine_places__settlements` |

The method is fully automatic; there is no way to correct individual settlements.

---

## 1. Settlements: manual edits (deferred)

**Need:** an expert's knowledge of where settlements are should win over the algorithm: remove false positives,
add small towns the method misses, reshape larger settlements.

### 1.1 Model: edits on top of the computed baseline

The automatic method stays the baseline; user-drawn polygons are applied as a final step, so they survive method
changes and rebuilds. Each polygon has one action:

| Action | Effect |
|---|---|
| `replace` | The drawn outline becomes the settlement: computed shapes overlapping it are clipped away, building count and footprint acres recomputed inside it. For reshaping towns and cities |
| `add` | A settlement where the method found none (a missed small town); overlapping computed shapes merge into it |
| `remove` | Computed settlements inside it are deleted (false positives: campgrounds, industrial parks) |

Optional properties: `name` (overrides "named after the town"), `note` (why, for the record), `author`, `date`.

### 1.2 Storage: a GeoJSON file in git

`data/edits/settlements.geojson` (EPSG:4326, one Feature per edit, properties as above).

- Reproducible: every rebuild re-applies the edits, on the workstation and on the AWS server.
- Reviewable: git history shows who changed what and when.
- The settlements SQL folds a checksum of the file into its rebuild check (next to `method_version` and the
  building count), so editing the file triggers a rebuild. Applying edits is cheap; the rebuild is the clustering.
- Loaded into a table (`src_units.settlement_edits`) by the seed before the settlement step.

### 1.3 Method step and documentation

- New final step in `030_settlements.sql`, after hole filling: `remove`, then `replace` (clip + recompute), then `add`.
- `docs/methods/settlements.json` gains a "Manual edits" step and a live count on /admin/methods
  (e.g. "14 replaced, 6 added, 9 removed").
- `pub.maine_places__settlements` gains a column `source` = `computed` | `edited`, so maps and the inspector can show
  which outlines a person drew.

### 1.4 Drawing tools (in order of effort)

1. **QGIS** (desktop): load the current settlements and buildings as a backdrop, draw with snapping, save the GeoJSON.
   Most capable; no new code.
2. **geojson.io** (browser): draw, set `action`, save. No install; basic.
3. **In-app editor** (`/admin/methods/settlements/edit`): draw on the real map beside settlements and footprints, pick an
   action, save through core-api (admin only, per the admin-only rule). About half a day; only worth it if edits
   become frequent. Saving needs a write path for the file (core-api mounts `data/edits` read-write, or edits go to the
   database and `make edits-export` writes the file for git).

Recommended order: pipeline + QGIS/geojson.io first; the in-app editor later if needed.

### 1.5 Open decisions

1. `replace` outlines: **exact** (used as drawn: full control) or **snapped** to the buildings inside (method's 10 m
   margin beyond the outermost walls: consistent with computed shapes, rough drawing is fine).
2. A `replace` that only partly overlaps a computed settlement: clip the rest away, or keep the uncovered part as its
   own settlement.
3. Whether edits apply to other classification layers later (same file pattern per layer).

### 1.6 Effort

Pipeline (table load, SQL step, checksum trigger, `source` column, method doc, tests): about half a day.
In-app editor: about half a day more.
