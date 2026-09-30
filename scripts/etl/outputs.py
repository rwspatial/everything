"""Discover what each dataset feeds, and where it is on the map.

For every src_* table a recipe loads (postgis_table output) this finds:
  pub views that depend on it (pg_depend) and pub SQL functions that reference it by name,
  the tiPG collections those become, and the projects (projects/*/project.json) that use them.
It also stores table stats, a coarse footprint (grid cells that contain data) and the coverage.
"""
from __future__ import annotations

import json
from pathlib import Path

GRID_CELLS = 48  # footprint resolution: 48 x 48 cells over the data extent


def project_usage(projects_dir: Path) -> dict[str, list[str]]:
    """collection id -> project slugs that draw it (to-do layers excluded)."""
    usage: dict[str, set[str]] = {}
    for manifest in sorted(projects_dir.glob("*/project.json")):
        try:
            m = json.loads(manifest.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for layer in m.get("layers", []):
            src = layer.get("source") or {}
            coll = src.get("collection") or src.get("cog")  # tiPG collection id, or COG name (titiler)
            if coll and layer.get("status") != "todo":
                usage.setdefault(coll, set()).add(m.get("slug", manifest.parent.name))
    return {k: sorted(v) for k, v in usage.items()}


def pub_dependents(conn, qualified: str) -> list[tuple[str, str]]:
    """[(pub object, 'pub_view' | 'pub_function')] built on a table."""
    views = conn.execute(
        """SELECT DISTINCT n.nspname || '.' || v.relname
           FROM pg_depend d
           JOIN pg_rewrite r ON r.oid = d.objid
           JOIN pg_class v ON v.oid = r.ev_class
           JOIN pg_namespace n ON n.oid = v.relnamespace
           WHERE d.refobjid = to_regclass(%s) AND v.oid <> d.refobjid AND n.nspname = 'pub'""",
        (qualified,),
    ).fetchall()
    # SQL function bodies are not tracked in pg_depend; match the qualified table name in the source.
    funcs = conn.execute(
        """SELECT DISTINCT n.nspname || '.' || p.proname
           FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'pub' AND p.prosrc ILIKE '%%' || %s || '%%'""",
        (qualified,),
    ).fetchall()
    return [(v[0], "pub_view") for v in views] + [(f[0], "pub_function") for f in funcs]


def table_stats(conn, qualified: str) -> dict | None:
    schema, table = qualified.split(".", 1)
    if not conn.execute("SELECT to_regclass(%s)", (qualified,)).fetchone()[0]:
        return None
    gc = conn.execute(
        "SELECT f_geometry_column, type, srid FROM geometry_columns WHERE f_table_schema = %s AND f_table_name = %s LIMIT 1",
        (schema, table),
    ).fetchone()
    q = f'"{schema}"."{table}"'
    estimate = conn.execute("SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(%s)", (qualified,)).fetchone()[0]
    rows = conn.execute(f"SELECT count(*) FROM {q}").fetchone()[0] if estimate < 1_000_000 else estimate
    size = conn.execute("SELECT pg_total_relation_size(to_regclass(%s))", (qualified,)).fetchone()[0]
    return {"row_count": rows, "bytes": size, "geom": gc[0] if gc else None,
            "geometry_type": gc[1] if gc else None, "srid": gc[2] if gc else None}


def footprint(conn, qualified: str, geom: str, srid: int) -> None:
    """Coarse footprint: union of grid cells (over the data extent) that contain any feature."""
    schema, table = qualified.split(".", 1)
    q, g = f'"{schema}"."{table}"', f'"{geom}"'
    conn.execute(
        f"""WITH ext AS (SELECT ST_SetSRID(ST_Extent({g})::geometry, %(srid)s) AS e FROM {q}),
                 params AS (SELECT e, GREATEST(ST_XMax(e) - ST_XMin(e), ST_YMax(e) - ST_YMin(e)) / %(n)s AS size FROM ext),
                 cells AS (SELECT (ST_SquareGrid(size, e)).geom AS cell FROM params WHERE size > 0),
                 hit AS (SELECT c.cell FROM cells c
                         WHERE EXISTS (SELECT 1 FROM {q} t WHERE t.{g} && c.cell AND ST_Intersects(t.{g}, c.cell))),
                 fp AS (SELECT ST_Multi(ST_Transform(ST_CollectionExtract(
                            ST_Intersection(ST_Union(cell), (SELECT e FROM ext)), 3), 4326)) AS geom FROM hit),
                 bb AS (SELECT ST_Transform(e, 4326)::box2d AS b FROM ext)
            UPDATE app.dataset_outputs o
               SET footprint = CASE WHEN ST_GeometryType(fp.geom) = 'ST_MultiPolygon' THEN fp.geom END,
                   bbox = bb.b
              FROM fp, bb
             WHERE o.kind = 'postgis_table' AND o.locator = %(loc)s""",
        {"srid": srid, "n": GRID_CELLS, "loc": qualified},
    )


def refresh_outputs(conn, recipe: str | None, projects_dir: Path) -> list[str]:
    """Update stats/footprints of postgis_table outputs and (re)discover derived outputs. Returns recipes touched."""
    usage = project_usage(projects_dir)
    rows = conn.execute(
        """SELECT recipe_name, locator FROM app.dataset_outputs
           WHERE kind = 'postgis_table' AND (%s::text IS NULL OR recipe_name = %s)""",
        (recipe, recipe),
    ).fetchall()
    touched = set()
    for recipe_name, locator in rows:
        stats = table_stats(conn, locator)
        if stats is None:
            conn.execute(
                "UPDATE app.dataset_outputs SET health = 'fail', health_detail = 'table no longer exists', "
                "health_checked_at = now() WHERE kind = 'postgis_table' AND locator = %s", (locator,))
            continue
        conn.execute(
            """UPDATE app.dataset_outputs SET row_count = %s, bytes = %s, geometry_type = %s, srid = %s
               WHERE kind = 'postgis_table' AND locator = %s""",
            (stats["row_count"], stats["bytes"], stats["geometry_type"], stats["srid"], locator),
        )
        if stats["geom"] and stats["srid"]:
            footprint(conn, locator, stats["geom"], stats["srid"])
        deps = pub_dependents(conn, locator)
        found = []
        table_projects: set[str] = set()
        for obj, obj_kind in deps:
            projects = usage.get(obj, [])
            table_projects.update(projects)
            note = "SQL function (dependency found by name)" if obj_kind == "pub_function" else None
            for kind, url in (("pub_view", None), ("tipg_collection", f"/tiles/collections/{obj}")):
                conn.execute(
                    """INSERT INTO app.dataset_outputs (recipe_name, kind, locator, public_url, projects, notes,
                                                        footprint, bbox, imported_by)
                       SELECT %s, %s, %s, %s, %s, %s, footprint, bbox, NULL FROM app.dataset_outputs
                       WHERE kind = 'postgis_table' AND locator = %s
                       ON CONFLICT (kind, locator) DO UPDATE SET recipe_name = EXCLUDED.recipe_name,
                           public_url = EXCLUDED.public_url, projects = EXCLUDED.projects, notes = EXCLUDED.notes,
                           footprint = EXCLUDED.footprint, bbox = EXCLUDED.bbox""",
                    (recipe_name, kind, obj, url, projects, note, locator),
                )
                found.append((kind, obj))
        conn.execute(
            "UPDATE app.dataset_outputs SET projects = %s WHERE kind = 'postgis_table' AND locator = %s",
            (sorted(table_projects), locator),
        )
        if recipe_name:
            # Forget derived outputs that no longer exist (e.g. a dropped view).
            keep = [f"{k}|{o}" for k, o in found]
            conn.execute(
                """DELETE FROM app.dataset_outputs WHERE recipe_name = %s AND kind IN ('pub_view', 'tipg_collection')
                   AND NOT (kind || '|' || locator = ANY(%s))
                   AND NOT EXISTS (SELECT 1 FROM app.dataset_outputs x WHERE x.recipe_name = %s
                                   AND x.kind = 'postgis_table' AND x.locator <> %s)""",
                (recipe_name, keep, recipe_name, locator),
            )
            touched.add(recipe_name)
    # COGs: which project layers point at them (source.cog); the tile URL shares the COG's projects.
    for cog, in conn.execute("SELECT locator FROM app.dataset_outputs WHERE kind = 'cog' "
                             "AND (%s::text IS NULL OR recipe_name = %s)", (recipe, recipe)).fetchall():
        conn.execute("UPDATE app.dataset_outputs SET projects = %s WHERE (kind = 'cog' AND locator = %s) "
                     "OR (kind = 'tile_url' AND locator = %s)",
                     (usage.get(cog, []), cog, f"/raster/{cog}/{{z}}/{{x}}/{{y}}.png"))
    for name in touched:
        refresh_coverage(conn, name)
    conn.commit()
    return sorted(touched)


def record_cog(conn, recipe: str, name: str, raster: dict, size: int, checksum: str, wgs84_geojson: str,
               run_id: int | None, projects_dir: Path) -> None:
    """Register a COG and its titiler tile URL as outputs (footprint = raster extent), then refresh coverage."""
    projects = project_usage(projects_dir).get(name, [])
    for kind, locator, url in (("cog", name, f"/raster/{name}/info"),
                               ("tile_url", f"/raster/{name}/{{z}}/{{x}}/{{y}}.png", None)):
        conn.execute(
            """INSERT INTO app.dataset_outputs (recipe_name, kind, locator, public_url, projects, raster, bytes, checksum,
                                                srid, loaded_run_id, imported_at, imported_by, footprint, bbox)
               VALUES (%(r)s, %(k)s, %(l)s, %(u)s, %(p)s, %(raster)s, %(b)s, %(c)s, %(srid)s, %(run)s, now(), current_user,
                       ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(fp)s), 4326)),
                       box2d(ST_SetSRID(ST_GeomFromGeoJSON(%(fp)s), 4326)))
               ON CONFLICT (kind, locator) DO UPDATE SET recipe_name = EXCLUDED.recipe_name,
                   public_url = EXCLUDED.public_url, projects = EXCLUDED.projects, raster = EXCLUDED.raster,
                   bytes = EXCLUDED.bytes, checksum = EXCLUDED.checksum, srid = EXCLUDED.srid,
                   loaded_run_id = EXCLUDED.loaded_run_id, imported_at = now(), imported_by = current_user,
                   footprint = EXCLUDED.footprint, bbox = EXCLUDED.bbox""",
            {"r": recipe, "k": kind, "l": locator, "u": url, "p": projects, "raster": json.dumps(raster),
             "b": size if kind == "cog" else None, "c": checksum if kind == "cog" else None,
             "srid": int(raster["crs"].split(":")[1]) if raster.get("crs") else None, "run": run_id, "fp": wgs84_geojson},
        )
    refresh_coverage(conn, recipe)


def refresh_coverage(conn, recipe: str) -> None:
    """Received = union of the dataset's table footprints. Requested is set from the recipe when it names an extent."""
    spec = conn.execute("SELECT coverage FROM app.recipes WHERE name = %s", (recipe,)).fetchone()
    spec = (spec[0] if spec else None) or {}
    extent = spec.get("extent") or "as published"
    requested_bbox = spec.get("bbox")
    conn.execute(
        """INSERT INTO app.coverages (recipe_name, extent_name, spec, requested_geom, received_geom, bbox,
                                      received_ratio, computed_at)
           SELECT %(r)s, %(extent)s, %(spec)s, req.g, rec.g, rec.b,
                  CASE WHEN req.g IS NOT NULL AND rec.g IS NOT NULL
                       THEN round((ST_Area(ST_Intersection(req.g, rec.g)::geography) / NULLIF(ST_Area(req.g::geography), 0))::numeric, 4)
                  END,
                  now()
           FROM (SELECT ST_Multi(ST_Union(footprint)) AS g, ST_Extent(footprint)::box2d AS b
                 FROM app.dataset_outputs WHERE recipe_name = %(r)s AND kind IN ('postgis_table', 'cog')) rec,
                (SELECT CASE WHEN %(bbox)s::float8[] IS NOT NULL
                             THEN ST_Multi(ST_MakeEnvelope((%(bbox)s::float8[])[1], (%(bbox)s::float8[])[2],
                                                           (%(bbox)s::float8[])[3], (%(bbox)s::float8[])[4], 4326)) END AS g) req
           ON CONFLICT (recipe_name) DO UPDATE SET extent_name = EXCLUDED.extent_name, spec = EXCLUDED.spec,
               requested_geom = EXCLUDED.requested_geom, received_geom = EXCLUDED.received_geom, bbox = EXCLUDED.bbox,
               received_ratio = EXCLUDED.received_ratio, computed_at = now()""",
        {"r": recipe, "extent": extent, "spec": json.dumps(spec), "bbox": requested_bbox},
    )
