# 06: Admin dashboard (dataset registry)

**http://localhost:8080/admin**: every dataset defined in `data/recipes/`, with where it is published, how fresh it
is, and every download/import run. Phase A is **read-only**: re-download, dry run and rebuild buttons arrive with the
job queue (Phase B). Until then, use the `make` commands; their runs appear in the dashboard.

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
| **Jobs & runs** (`/admin/jobs`) | Active jobs and recent runs, refreshed every 5 s |
| **Run** (`/admin/runs/<id>`) | Who ran it and how, duration, rows, bytes, parameters, error, and the last 16 KB of its log (**secrets redacted**) |

## Where the data comes from

| Registry table | Filled by |
|---|---|
| `app.recipes` | `make recipes-sync`, and automatically at the start of every import command. The YAML stays the source of truth |
| `app.runs`, `app.jobs` | Every `make import-recipe`, `make import-all`, `make import` and `make cog` |
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
freshness: { method: http_head, every: 30d }
attribution: Made with Natural Earth
```

Existing recipes without these fields still work. The dashboard falls back to `description` and the source URL.

## API keys

Keys live only in `.env` and are passed only to the containers that call external services (geotools today, the worker
in Phase B). The admin API never receives them, and the dashboard shows only whether each key is configured. A recipe
whose `requires_keys` names a missing key fails immediately with a message naming the key.

## Leaving localhost

Basic auth over plain HTTP is for local use only. When deployed: TLS, and single sign-on (OIDC) in place of the password,
either ALB OIDC authentication or `oauth2-proxy` behind the same `forward_auth` hook.
See `.claude/plans/admin-dashboard.plan.md` §8.
