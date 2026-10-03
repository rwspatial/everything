# 06: Admin dashboard (dataset registry)

**http://localhost:8080/admin**: every dataset defined in `data/recipes/`, with where it is published, how fresh it
is, and every download/import run. Each dataset page has **Actions** (check for updates, dry run, re-import,
re-download, re-check health, enable/disable). The **dataset worker** runs them from a job queue (`make workers-up`);
the same `make` commands still work, and every run appears in the dashboard either way.

## Logging in

```bash
make admin-credentials      # prints the user and password from .env (creates them in an older .env)
```

The browser asks for them on the first `/admin` visit. `/admin` and `/api/admin/*` return **401** without them. The public
site (`/`, `/p/…`, `/tiles/…`, `/projects/…`) is unaffected.

How it works: Caddy sends every `/admin*` and `/api/admin/*` request to core-api's `/api/admin/auth` first
(`forward_auth`), and core-api checks the credentials again on every API call. To change the password, edit
`ADMIN_PASSWORD` in `.env`, then run `make up`.

## What each page shows

| Page | Content |
|---|---|
| **Datasets** (`/admin`) | One row per recipe: status (ok, stale, unhealthy, failed, disabled), freshness, output health, coverage, feature count, size in PostGIS, projects using it, last run. Filters: search, kind, group, status, stale only. Ad hoc `make import` tables are listed separately |
| **Dataset** (`/admin/datasets/<name>`) | Coverage map (footprint of where data actually is) and bbox; source, license, **attribution text** (copy button), vintage, stored CRS, geometry, checksum, API keys needed; freshness (what we hold vs what upstream offers now); **outputs and health** (the `src_*` table, the `pub` views and functions built on it, their tiPG collections, the projects that draw them); run history; the recipe YAML |
| **Jobs & runs** (`/admin/jobs`) | Active jobs (with Cancel) and recent runs, refreshed every 5 s. Runs show who started them: `admin:<user>` (dashboard), `scheduler`, or `cli:<user>` |
| **Run** (`/admin/runs/<id>`) | Who ran it and how, duration, rows, bytes, parameters, error, and the last 16 KB of its log (**secrets redacted**) |

## Actions and the dataset worker

Each button on a dataset page queues a job; the dataset worker (`dataset-worker`, same image and mounts as geotools,
`loader` role, no Docker socket) runs it with `scripts/geoimport.py` and records the run.

| Button | Runs | Notes |
|---|---|---|
| Check for updates | `geoimport.py freshness <name>` | ETag / Last-Modified (files) or last-edit date (ArcGIS) against what we hold |
| Dry run | `geoimport.py plan <name>` | Upstream size and version vs the cached download, current rows; changes nothing |
| Re-import | `geoimport.py recipe <name>` | From the cached download (ArcGIS and Census sources are always fetched again) |
| Re-download and import | `geoimport.py recipe <name> --redownload` | Asks for confirmation; the cached copy is replaced only by a complete download |
| Re-check health | `geoimport.py health <name>` | Table, published views, tiPG collection, COG/tiles |
| Enable / Disable | `geoimport.py set-enabled <name> true|false` | Edits `enabled:` in the recipe YAML (commit it); disabled recipes cannot be imported |

How jobs run:
- **Concurrency.** Slots per class: 2 downloads (`network`), 1 raster rebuild (`raster_heavy`) and 1 database job
  (`db`). Several workers can share the queue (`FOR UPDATE SKIP LOCKED`).
- **Duplicates.** A second click while a job for the same dataset is queued or running returns that job.
- **Retries.** Failed imports, re-downloads and update checks are retried with growing delays (30, 60, 120 s; 3, 6,
  12 s in dev) up to 4 attempts. The job then fails with the error line from the log.
- **Cancel.** Stops the import within seconds (Jobs page or the dataset page). A partial download is removed, the
  table keeps its previous contents, and the run is recorded as cancelled.
- **Safe replacement.** Imports swap in a staging table when published views depend on the table, so maps keep
  working during and after a re-import.
- **Scheduler** (every 5 minutes):
  - an update check when a recipe's `freshness.every` (e.g. `30d`) has passed;
  - a health check per dataset every 24 h;
  - for recipes with `freshness: { auto_refresh: true }`, a re-download when the check says upstream changed.
  Set `DATASET_SCHEDULER=off` in `.env` to switch it off.
- **Lost workers.** If a worker stops heartbeating for 60 s, its jobs are requeued or failed by the next worker.

```bash
make workers-up      # start the dataset worker (and the analysis worker)
make workers-logs    # follow them
```

## Where the data comes from

| Registry table | Filled by |
|---|---|
| `app.recipes` | `make recipes-sync`, and automatically at the start of every import command. The YAML stays the source of truth |
| `app.runs`, `app.jobs` | Every `make import-recipe`, `make import-all`, `make import` and `make cog`, and every dashboard or scheduled job (`kind = 'dataset'`) |
| `app.dataset_outputs` | Imports (the table) plus discovery: `pub` views that depend on it (`pg_depend`), `pub` SQL functions that name it, their tiPG collections, and `projects/*/project.json` usage |
| `app.coverages` | Footprint: grid cells (48 × 48 over the data extent) that contain features |
| `app.dataset_parts`, `app.freshness_checks` | `make freshness`: ETag / Last-Modified of the upstream file vs what we downloaded |
| `app.secrets_status` | Whether each API key is configured in the processes that use it (fingerprint only, never the value) |

`app.datasets` still exists as a compatibility view over `app.dataset_outputs`.

## Commands

| Command | Does |
|---|---|
| `make recipes-sync` | Mirror the recipe YAMLs into the registry |
| `make health-datasets [r=<recipe>]` | Re-discover outputs and re-check health: table has rows, `tipg_ro` can read the view, tiPG serves the collection and returns data; a COG opens with COG layout, and TiTiler renders a tile and answers a point query |
| `make freshness [r=<recipe>]` | Ask upstream whether the data changed since our download |
| `make admin-credentials` | Show (or create) the admin login |

## Recipe fields the dashboard reads (recipe format v2, all optional)

```yaml
title: Lakes (1:10m)
agency: Natural Earth (naturalearthdata.com)
group: natural-earth
vintage: { label: "Natural Earth 1:10m physical vectors" }
coverage: { extent: world }        # or bbox: [w, s, e, n] to get a requested-vs-received ratio
requires_keys: []                  # e.g. [CENSUS_API_KEY]; runs fail fast when a key is missing
freshness: { method: http_head, every: 30d }   # add auto_refresh: true to re-download automatically when upstream changes
attribution: Made with Natural Earth
```

Existing recipes without these fields still work. The dashboard falls back to `description` and the source URL.

## API keys

Keys live only in `.env` and are passed only to the containers that call external services (geotools and the
dataset worker). The admin API never receives them, and the dashboard shows only whether each key is configured. A recipe
whose `requires_keys` names a missing key fails immediately with a message naming the key.

## Leaving localhost

Basic auth over plain HTTP is for local use only. When deployed: TLS, and single sign-on (OIDC) in place of the password,
either ALB OIDC authentication or `oauth2-proxy` behind the same `forward_auth` hook.
See `.claude/plans/admin-dashboard.plan.md` §8.
