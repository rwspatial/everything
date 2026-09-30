# Spatial app generator

A modular web-mapping stack: **PostGIS → tiPG → (Svelte + MapLibre)**, with a GDAL + R + Python toolbox for data work.
Adding a map project means registering database views plus a manifest. No frontend code changes are needed.

- Architecture diagrams (current + proposed): [docs/architecture.md](docs/architecture.md)
- Architecture plan: [.claude/plans/spatial-app-architecture.plan.md](.claude/plans/spatial-app-architecture.plan.md)
- Operator guide: [docs/setup/](docs/setup/README.md)
- Decisions: [docs/decisions/](docs/decisions/)

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Docker, PostGIS, tiPG, proxy, geotools, data import, setup guide | done: exit gate passed 2026-09-29 |
| 2 | Svelte + MapLibre UI shell, placeholder projects | done: exit gate passed 2026-09-29 |
| Dashboard A | `/admin`: dataset registry, run history, freshness, health (read-only) | done 2026-09-30 |
| 3 | Project creator (`mapgen`, core-api) | – |
| 4 | MCP servers | – |
| 5 | R / Python ML workers | – |
| 6 | AWS (Terraform, RDS) | deferred |

## Quick start (WSL2 + Docker)

```bash
make env         # .env with random passwords
make bootstrap   # start stack, build geotools, import Natural Earth, create views
make verify
```

Then open **http://localhost:8080/** (landing page; **/maps** is the project hub → map viewer). Site name, copy and contact details live in `frontend/src/lib/site.ts`. `make help` lists every command.

## Layout

```
compose.yaml, compose.dev.yaml   stack definition (dev overlay enabled via .env)
Makefile                         every operator command
db/migrations/                   schema, roles, grants (dbmate)
db/seed/                         pub views for the placeholder projects
data/recipes/                    reproducible imports (committed)
data/incoming/                   raw files to import (gitignored)
services/geotools/               GDAL + R + Python image
services/proxy/Caddyfile         local reverse proxy
scripts/                         geoimport.py, ops.sh, verify
docs/setup/, docs/decisions/     operator guide, ADRs
analysis/                        your R / Python scripts (run in geotools)
```
