# 02: Containers

## What runs

| Service | Image (pinned in `.env`) | Role | Long-running? |
|---|---|---|---|
| `postgis` | `postgis/postgis:17-3.5` | Database. Data lives in the Docker volume `spatial_pgdata` | yes |
| `migrator` | `ghcr.io/amacneil/dbmate:2.36.0` | Applies `db/migrations`, sets role passwords, runs `db/seed` on demand | no, runs once per `make up` and exits 0 |
| `tipg` | `ghcr.io/developmentseed/tipg:1.6.1` | Serves `pub.*` as OGC Features + vector tiles | yes |
| `proxy` | `caddy:2.11.4-alpine` | The only published web port. Routes `/tiles/*` to tipg | yes |
| `geotools` | built locally from `services/geotools/` | GDAL + R + Python toolbox for imports and analysis | no, one-off via `make` |

Start order is enforced: postgis healthy → migrator exits successfully → tipg healthy → proxy.
If the migrator fails, `make up` stops and prints its log.

### Networks

| Network | Members | Internet? |
|---|---|---|
| `edge` | proxy (published on 127.0.0.1) | yes |
| `api` | proxy, tipg | no (internal) |
| `data` | postgis, migrator, tipg, geotools | no (internal) |
| `egress` | geotools | yes, for dataset downloads |
| `devhost` | postgis (dev profile only) | publishes 127.0.0.1:5433 |

## Everyday commands

| Command | Does |
|---|---|
| `make up` | Start everything and wait until healthy. Safe to repeat. |
| `make down` | Stop and remove containers. **Data is kept.** |
| `make stop` / `make start` | Pause and resume without removing containers. |
| `make restart` / `make restart s=tipg` | Restart all services, or one. |
| `make refresh` | Restart tipg so it sees new or changed `pub` views. |
| `make ps` / `make health` | State and health per service. |
| `make logs` / `make logs s=tipg` | Follow logs (Ctrl-C to stop). |
| `make shell s=postgis` | Shell inside a running container. |
| `make psql` | psql as the owner. `make psql r=analyst` (read-only), `r=loader`, `r=tipg`. |
| `make rebuild s=<svc>` | Recreate a container from a fresh image. |
| `make pull` | Download the pinned images again. |
| `make migrate` / `make migrate-status` | Apply pending migrations or show status. |
| `make r` / `make py` / `make tools-sh` | R, Python, or bash in geotools, already connected to PostGIS. |

## Profiles: dev vs locked

`.env` sets `COMPOSE_FILE=compose.yaml:compose.dev.yaml`. The dev overlay:
- publishes PostGIS on `127.0.0.1:5433` (for QGIS and host tools),
- enables tiPG debug mode (`/tiles/rawcatalog`) and a 30 s catalog refresh,
- turns off HTTP caching of tiles and styles (`TIPG_CACHECONTROL=no-cache`), so the browser never shows stale data.
  The locked profile uses tiPG's default `public, max-age=3600`.

For the locked profile, set `COMPOSE_FILE=compose.yaml` and run `make up`. PostGIS is then unreachable from the host,
and `make verify` checks that.

## Upgrading a pinned version

1. Edit the tag in `.env` **and** `.env.example`, and record why in `docs/decisions/0001-version-pins.md`.
2. `make pull && make up`. For `ROCKER_TAG`, also run `make build-tools`.
3. `make verify`.

PostGIS major upgrades (e.g. 17 → 18) need a dump/restore: `make backup`, change the tag, `make reset-db`, then `make restore b=...`.
