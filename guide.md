/plan, /tdd, /security-review, /build-fix, /refactor

claude --continue

wsl --shutdown

## PostGIS (DBeaver / QGIS)

host localhost, port 5433, database spatial (passwords in .env)

- analyst_ro (ANALYST_DB_PASSWORD): read-only, use for reviewing data
- gis_owner (POSTGRES_PASSWORD): owns everything, use only to see the whole database or change something
- tipg_ro, app_rw, loader, worker_rw: service logins, not for manual use

schemas:
- src_ne: raw Natural Earth imports
- pub: published layers served by tiPG (functions like rivers_by_rank are under pub -> Functions)
- app.datasets: list of loaded datasets
- public.schema_migrations: dbmate migration history

## URLs (proxy on localhost:8080)

- http://localhost:8080/tiles/collections
- http://localhost:8080/tiles/collections/{id}/viewer.html
- http://localhost:8080/tiles/api.html
- http://localhost:8080/healthz