# ADR 0001: Version pins (Phase 1)

Date: 2026-09-29. Status: accepted.

Versions are pinned in `.env` / `.env.example` and bumped deliberately (docs/setup/02-containers.md, "Upgrading").

| Component | Pin | Why this one |
|---|---|---|
| PostGIS | `postgis/postgis:17-3.5` | PostgreSQL 17 + PostGIS 3.5 is offered by **RDS for PostgreSQL** (Phase 6 target). `18-3.6` exists on Docker Hub but is newer than we need, and RDS availability should be re-checked before moving. **Re-check RDS engine versions before Phase 6.** |
| tiPG | `ghcr.io/developmentseed/tipg:1.6.1` | Latest (2026-09-03). The 1.x API is stable. Tile/TileJSON paths are `/collections/{id}/tiles/{tms}/...` since 1.0 |
| Caddy | `caddy:2.11.4-alpine` | Latest 2.11 patch. Only used locally |
| dbmate | `ghcr.io/amacneil/dbmate:2.36.0` | Latest (2026-09-19). The image includes `psql`, so it doubles as the seed runner |
| rocker/geospatial | `4.6.1` | R 4.6.1 on Ubuntu 24.04 (noble). System GDAL 3.8.x / PROJ 9.4 / GEOS from Ubuntu. Includes sf, terra, stars, spdep, gstat, and RStudio Server (unused for now) |
| Python stack | `services/geotools/requirements.txt` | Conservative pins compatible with GDAL 3.8 and numpy<2. GDAL-linking packages built from source |

## Consequences

- **The `postgis/postgis:17-3.5` image is built on an old Debian base: PROJ 7.2.1, GEOS 3.9.0** (found 2026-09-29).
  PROJ 7 refuses to transform latitudes of ±90° to Web Mercator, so global polygons reaching the poles make tiles fail
  ("tolerance condition error"). Mitigation: the `clip_web_mercator` import option (docs/setup/04). GEOS 3.9 also lacks
  some newer functions (e.g. `ST_CoverageUnion`). Revisit before Phase 6: check for a newer-base 17-3.5 tag, and note that
  RDS ships newer PROJ/GEOS, so local and cloud behaviour differ slightly.
- GDAL in geotools is **3.8.x** (Ubuntu noble), not the newest GDAL. That's intentional: one GDAL shared by R, Python, and the CLI
  beats the newest GDAL in only one of them. Revisit when rocker moves to a newer Ubuntu base.
- tiPG has PostGIS encode vector tiles (`ST_AsMVT`), and its image doesn't use GDAL, so the tiPG version is independent of geotools.
