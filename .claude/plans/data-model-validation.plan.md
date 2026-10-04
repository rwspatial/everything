# Data model & validation — Plan

Status: **deferred (2026-10-04)**: idea noted, not scheduled. Related: `classification.plan.md` (derived layers),
admin Database page (`/admin/database`), `make verify`.

## Decision so far

A PostGIS data model for the existing data, used for **validation, not enforcement**:

- **No foreign keys / enforced constraints between `src_*` tables.** Imports replace a source table wholesale; FKs
  would block TRUNCATE/replace, force a load order, and re-validate whole relations on every refresh (locks on both
  tables while 745k parcels or 925k buildings are scanned, stalling tiles). Sources also legitimately disagree (e.g.
  retired USGS gauges), so a hard rule would reject good imports.
- **Normalization has little to gain:** each source is one agency's dataset with its own keys; the joins already live
  in the `pub` views.

## When picked up

1. **Document the logical model**: shared keys (census GEOIDs, SSURGO `mukey`, `unit_key`, `town_geoid`, USGS
   `monitoring_location_id`) and which views join on them, as a short doc with an ERD.
2. **Non-blocking validation checks** run after each import and in `make verify`, shown with the dataset's health on
   the admin Datasets/Database pages; only real regressions fail `verify`. About 15 to start:
   - join coverage with thresholds. Baseline 2026-10-04: parcels with a town 99.99 % (40 missing); SSURGO polygons
     with a map unit 100 %; towns and tracts with ACS rows 100 %; gauge sites with a recent reading 12.9 % (expected:
     most sites are retired)
   - key uniqueness; row-count drift vs the previous import; value domains (drainage classes, CDL codes); geometry
     validity and SRID
3. **Reduction in derived tables** (rebuilt only when inputs or method change, like settlements): simplified statewide
   wetlands (the zoom-11 gap), generalized outlines for low zooms, dropping unused columns at import.
4. **Check the big imports' swap pattern**: table recipes TRUNCATE + refill in one transaction (ACCESS EXCLUSIVE until
   commit, so tile reads wait during the reload). Fine for small census tables; large tables should load into a
   staging table and swap with a rename (a momentary lock).
