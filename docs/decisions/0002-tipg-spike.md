# ADR 0002: tiPG spike results

Date: 2026-09-29. Status: **confirmed live** against tiPG 1.6.1 (pip, uvicorn, 2 workers) behind the project Caddyfile,
on a scratch PostgreSQL + PostGIS (conda-forge, PG 18.6 / PostGIS 3.6 rather than the pinned 17/3.5; the migrations,
seeds and grants are version-agnostic), then on the pinned Docker stack (`make verify` all green, 2026-09-29).

| Question (plan §4, Phase 1) | Answer | Source | Checked by `make verify` |
|---|---|---|---|
| Endpoint paths | `/collections`, `/collections/{id}`, `/collections/{id}/queryables`, `/collections/{id}/items[/{fid}]`, `/collections/{id}/tiles/{tms}/{z}/{x}/{y}`, `/collections/{id}/tiles/{tms}/tilejson.json`, `/collections/{id}/tiles/{tms}/style.json`, `/collections/{id}/viewer.html`, `/healthz` | tiPG docs `user_guide/endpoints.md`, CHANGES 1.0.0 | tile, tilejson, items fetched via the proxy |
| MVT `source-layer` name | With `TIPG_SET_MVT_LAYERNAME=TRUE`, tiles name their layer by TABLE name (`world_overview__countries`), but tilejson `vector_layers[].id` and style.json say `pub.world_overview__countries` (`collections.py:1048` uses `self.table`; `factory.py:1783/1889` use `collection.id`). Result: **tiPG's own viewer.html draws nothing** (seen live 2026-09-29). With FALSE (the default) both paths use `"default"`. **Decision: `TIPG_SET_MVT_LAYERNAME=FALSE`; contract: `source-layer` = `"default"`.** Each tiPG source carries one collection, so this is unambiguous | tiPG 1.6.1 source, raw protobuf decode, the live viewer | tile layer and style.json source-layer must both be `default` |
| Function args on tile requests | Function args named `z`, `x`, `y` are filled from the tile path. A `bounds` arg gets the tile bbox. All other args come from **query parameters** by name. Args without defaults are required | docs `advanced/functions.md` | `rivers_by_rank` tiles with `max_scalerank=2` vs `10` must differ |
| Catalog refresh after new views | The catalog is cached for `TIPG_CATALOG_TTL` seconds (default 300) and refreshed by middleware on the next request after expiry. `/refresh` exists only with `TIPG_DEBUG=TRUE`, **and only refreshes the worker process that handled the request**. Decision: dev TTL 30 s. `make refresh` restarts tipg (reaches all workers) | tipg `main.py`, `settings.py` | view list checked after `make refresh` |
| Serving behind `/tiles` | `TIPG_ROOT_PATH=/tiles` + Caddy `handle_path /tiles/*` (strips the prefix) | docs `configuration.md` (APISettings) | tilejson URLs must start with `http://localhost:8080/tiles/` |
| Tile performance baseline (p95 at z10/z14) | Docker stack, via proxy, 60 random tiles per layer/zoom over populated areas, 4 concurrent, dev profile (no HTTP cache). **p95: z4 17–46 ms, z10 14–20 ms, z14 15–23 ms; p50 11–16 ms; 0 errors** across all 4 layers. Natural Earth is small (most z10/z14 tiles are nearly empty), so this is a regression baseline, not a capacity figure. Re-measure with the first real dataset | measured 2026-09-29 | not automated |

## Live results (scratch run, 2026-09-29)

| Check | Result |
|---|---|
| `/tiles/collections` through Caddy | exactly the 5 `pub.*` collections |
| z0 tile, `pub.world_overview__countries` | 200, `application/vnd.mapbox-vector-tile`, 35 KB, 177 features (layer `world_overview__countries` under TRUE; `default` after the switch to FALSE) |
| Function tile `rivers_by_rank`, `max_scalerank=2` vs `10` | 62 vs 1461 features. Query parameters reach the function, and its SRID-less geometry output is placed correctly |
| TileJSON `tiles[0]` | `http://localhost:18080/tiles/collections/...`, so the `/tiles` root path is honoured |
| Items `bbox=-10,35,30,60` | `numberMatched=42`, equal to `ST_Intersects` count in SQL |

## Decisions

- `TIPG_DB_SCHEMAS='["pub"]'`: tiPG never sees `src_*`, `app`, or `ml_out`. It also connects as `tipg_ro`, which has
  no privileges outside `pub`, so the boundary is enforced twice.
- `pub` SQL functions are `SECURITY DEFINER` with `SET search_path = pg_catalog, public`. Otherwise `tipg_ro`
  would need direct read access to `src_*`.
- ~~Open risk: SRID of a function's geometry output~~. Resolved: function tiles render the expected feature counts.
- Consider reporting the TRUE-mode tilejson/tile layer-name mismatch upstream (developmentseed/tipg). We don't depend
  on a fix, because FALSE is consistent.
