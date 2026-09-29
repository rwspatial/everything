# 99: Troubleshooting

### `docker: command not found` / "could not be found in this WSL 2 distro"
Docker Desktop's WSL integration is off for this distro. Go to *Settings → Resources → WSL integration*, enable it,
click *Apply & restart*, then reopen the WSL shell. Or install Docker Engine inside WSL (01-install.md, option B).

### `make: command not found`
`sudo apt update && sudo apt install -y make`

### `.env missing`
Run `make env`. Don't copy `.env.example` by hand, because it contains `changeme` placeholders.

### Port already in use (`bind: address already in use`)
Another program uses 8080 or 5433, perhaps a Windows PostgreSQL or another dev server.
Change `HTTP_PORT` / `PG_HOST_PORT` in `.env`, then run `make up`. To find the culprit in PowerShell: `netstat -ano | findstr :8080`.

### `make up` says "migrator failed"
The migrator's log is printed. Common causes:
- **Owner password changed in `.env` after the database was created.** See 03-reinstall-reset.md, "Changing passwords".
- **A migration has an SQL error.** Fix the file and run `make up` again. dbmate runs each migration in a transaction.

### A new view doesn't show up in `/tiles/collections`
- Run `make refresh` (restarts tipg). The dev profile also re-reads every 30 s.
- The view must be in `pub`, have a geometry column with an SRID, and be readable. Check with `make psql r=tipg`,
  then `SELECT * FROM pub.<view> LIMIT 1;`.
- See what tiPG sees (dev profile): http://localhost:8080/tiles/rawcatalog

### A tile returns HTTP 500, and `make logs s=tipg` shows "transform: tolerance condition error (-20)"
The layer has geometry beyond Web Mercator's ±85.0511° latitude (typically Antarctica at −90°). The PostGIS image's
PROJ 7.2 cannot project it. Re-import with `clip=1` (recipe: `clip_web_mercator: true`), then `make refresh`.

### Tiles are empty in the map, but items return data
- Every tiPG tile layer is named **`default`** (`TIPG_SET_MVT_LAYERNAME=FALSE`), so a MapLibre `source-layer` must be
  `default`. Don't set it to TRUE: tiPG 1.6.1 then names tile layers `world_overview__countries` while its
  style.json says `pub.world_overview__countries`, and even tiPG's own viewer draws nothing (docs/decisions/0002).
- Check the layer's zoom range. tiPG defaults to 0–22.

### Scripts fail with `$'\r': command not found`
Windows line endings. `.gitattributes` forces LF, but files edited or copied from Windows can still break. Fix with
`sed -i 's/\r$//' scripts/*.sh`, and keep the repo on the Linux filesystem.

### Import: "schema src_x does not exist"
New domains need a migration: `make migration n=src_x`, add `CALL app.ensure_src_schema('src_x');`, then `make migrate`.

### Import: "has dependent views … different structure"
See 04-data-import.md, "Re-importing an existing table".

### Import: invalid geometries reported
Re-run with `fix=1`, or set `fix_invalid: true` in the recipe. Invalid polygons can drop out of tiles or break spatial joins.

### geotools build fails
- Out of memory: raise `memory=` in `.wslconfig` (01-install.md).
- Network or download errors: re-run `make build-tools`. Completed layers are cached.
- A Python package fails to compile against the system GDAL: note the package and version in the error. The pins
  are in `services/geotools/requirements.txt` (numpy stays <2 for GDAL 3.8 bindings).

### Files in `data/` or `analysis/` owned by root
geotools runs as your user (`HOST_UID`/`HOST_GID`, set by the Makefile). Running `docker compose run geotools` directly,
without make, uses UID 1000. Fix ownership with `sudo chown -R $USER: data analysis`.

### Disk filling up
`docker system df` shows usage. `docker image prune` removes dangling images, and `make nuke all=1` removes everything this project built.
