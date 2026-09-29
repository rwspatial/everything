# 01: Install

## Prerequisites (Windows + WSL2)

| Need | Check | Install |
|---|---|---|
| WSL2 with Ubuntu | `wsl -l -v` (PowerShell) shows VERSION 2 | `wsl --install -d Ubuntu` |
| Docker reachable **from inside WSL** | `docker version` and `docker compose version` in the WSL shell | Option A or B below |
| make | `make --version` | `sudo apt update && sudo apt install -y make` |
| git, curl, python3 | `git --version; curl --version; python3 --version` | `sudo apt install -y git curl python3` |

**Docker, option A: Docker Desktop (simplest on Windows).**
Install Docker Desktop, then go to *Settings → Resources → WSL integration*, enable your distro, and click *Apply & restart*.
If `docker` in WSL prints *"could not be found in this WSL 2 distro"*, this toggle is off.

**Docker, option B: Docker Engine inside WSL (no Desktop).**
Follow the Docker Engine install for Ubuntu (docs.docker.com/engine/install/ubuntu), then
`sudo usermod -aG docker $USER`, and restart the WSL shell. Enable systemd in `/etc/wsl.conf` if the daemon doesn't start.

**Where the repo lives:** keep it on the Linux filesystem (`/home/<you>/...`), **not** `/mnt/c/...`.
Bind mounts from `/mnt/c` are slow and break file permissions.

**Memory:** the geotools build and PostGIS like room. In `%UserProfile%\.wslconfig` on Windows:
```ini
[wsl2]
memory=8GB
```
Then run `wsl --shutdown` from PowerShell and reopen the shell.

**Disk:** plan for about 10 GB: geotools image ~5 GB, PostGIS/tiPG/Caddy images ~1 GB, plus data.

## First install

```bash
cd ~/projects/everything
make env           # creates .env (gitignored) with random passwords
make bootstrap     # see below
make verify
```

`make bootstrap` runs these steps, each of which is also its own target:

1. `make up`: pulls pinned images and starts **postgis → migrator → tipg → proxy** in order. The migrator applies
   `db/migrations` and sets each service role's password from `.env`.
2. `make build-tools`: builds the geotools image (GDAL + R + Python). **Takes 10–30 minutes the first time**,
   then it's cached. Only skipped when the image already exists.
3. `make import-all`: downloads Natural Earth into `data/cache/downloads/` and imports each recipe in `data/recipes/`.
4. `make seed`: creates the `pub.*` views for the placeholder projects.
5. `make refresh`: restarts tiPG so it lists the new views.

## Check it works

- `make verify` ends with `verify: ALL CHECKS PASSED`.
- http://localhost:8080/ shows a text landing page. The Svelte app arrives in Phase 2.
- http://localhost:8080/tiles/collections lists only `pub.*` collections.
- Map preview: http://localhost:8080/tiles/collections/pub.world_overview__countries/viewer.html
- `make datasets` shows 4 Natural Earth tables with row counts.

## What you now have

| URL / port | What |
|---|---|
| `http://localhost:8080/` | Caddy proxy (the only web entry point) |
| `http://localhost:8080/tiles/...` | tiPG: OGC API Features + vector tiles |
| `127.0.0.1:5433` (dev profile only) | PostGIS for QGIS, host psql, or host R/Python. Users and passwords are in `.env` |

Both ports bind to `127.0.0.1` only, so nothing is exposed to your network. To change ports, edit `HTTP_PORT` and `PG_HOST_PORT` in `.env`, then run `make up`.

## Connecting QGIS (optional)

*Layer → Data Source Manager → PostgreSQL → New*: host `localhost`, port `5433`, database `spatial`.
For browsing, use user `analyst_ro` with `ANALYST_DB_PASSWORD` from `.env` (read-only).
