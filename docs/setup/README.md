# Operator setup guide

A living guide: each phase adds sections, and every phase ends with a walkthrough from a clean clone.
Every command here is a `make` target. `make help` prints the same list.

| Guide | Covers | Phase |
|---|---|---|
| [01-install.md](01-install.md) | Prerequisites (WSL2, Docker, make), first install, verification | 1 |
| [02-containers.md](02-containers.md) | What runs where, and starting, stopping, restarting, logs, shells | 1 |
| [03-reinstall-reset.md](03-reinstall-reset.md) | Backups, restores, and the reset ladder from restart to full reinstall | 1 |
| [04-data-import.md](04-data-import.md) | Loading data with GDAL/ogr2ogr, recipes, publishing a view, R and Python access | 1 |
| [05-frontend.md](05-frontend.md) | The web app, adding projects (JSON only), dev server, browser tests | 2 |
| [06-admin.md](06-admin.md) | Admin dashboard: dataset registry, run history, freshness, health, login | Dashboard A |
| [07-projects.md](07-projects.md) | Creating projects: `./mapgen`, the `/admin/new` wizard, validation codes, the project registry | 3 |
| [08-mcp.md](08-mcp.md) | MCP servers for Claude Code: the read-only spatial-db server, credentials, testing | 4 |
| 09-ml-workers.md | R/Python workers | 5 |
| [99-troubleshooting.md](99-troubleshooting.md) | Known problems and fixes | all |

## Five-minute version

```bash
make env          # .env with random passwords
make bootstrap    # start, build geotools (slow, once), import Natural Earth, create views
make verify       # automated checks; expect "ALL CHECKS PASSED"
```

Then open **http://localhost:8080/** for the landing page; the project hub and map viewer are at **/maps**.
