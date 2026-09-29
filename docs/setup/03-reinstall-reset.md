# 03: Reinstall and reset

## Backups

```bash
make backup                                      # -> data/backups/spatial-<UTC timestamp>.dump
make restore b=data/backups/spatial-20260929T120000Z.dump
```

- Backups are `pg_dump -Fc` (compressed, custom format) of the whole `spatial` database.
- `restore` asks you to type `restore`, drops and recreates the database, restores the file, then re-runs migrations
  (so newer migrations apply and role passwords match the current `.env`).
- Roles are cluster-level and not in the dump. They're created by migrations, so a restore needs `make up` to have run.
- `data/backups/` is gitignored. Copy important dumps somewhere else too.

## The reset ladder

Use the lowest step that fixes the problem. Each step is more destructive than the one before.

| Step | Command | Fixes | Data |
|---|---|---|---|
| 1. Restart | `make restart` (or `s=tipg`) | Hung service, tiPG not seeing new views | kept |
| 2. Recreate containers | `make down && make up` | Changed `.env` or compose files, odd container state | kept |
| 3. Reset database | `make reset-db` | Broken schema, messy experiments, starting data over | **rebuilt from recipes** |
| 4. Full reinstall | `make nuke` then `make bootstrap` | "Start from scratch" | **rebuilt from recipes** |

### Step 3: `make reset-db`

1. Lists datasets that have **no recipe**. **These are lost.** Write a recipe first (see 04-data-import.md).
2. Asks you to type `reset`.
3. Takes a backup automatically (skip with `BACKUP=no make reset-db`).
4. Deletes the `spatial_pgdata` volume, starts the stack (migrations recreate schemas and roles),
   then runs `import-all`, `seed`, and `refresh`.

### Step 4: `make nuke`

Removes containers, all project volumes, `data/cog/`, and verification output. **Kept:** `data/incoming/`, `data/backups/`,
`data/cache/downloads/`, `.env`, and the geotools image (so reinstalling skips the long build).
`make nuke all=1` also removes the images, including geotools.

Then:
```bash
make bootstrap && make verify
```

## Changing passwords

- **Service roles** (`TIPG_`, `APP_`, `LOADER_`, `WORKER_`, `ANALYST_DB_PASSWORD`): edit `.env`, then run `make up`.
  The migrator re-sets them on every start.
- **Owner** (`POSTGRES_PASSWORD`): only applied when the volume is first created. Either change it in the database
  (`make psql`, then `ALTER ROLE gis_owner PASSWORD '...';`) and in `.env` together, or run `make reset-db` after editing `.env`.

## Non-interactive use

`CONFIRM=yes` skips the typed confirmations, e.g. `CONFIRM=yes BACKUP=no make reset-db`. Only use it when you mean it.
