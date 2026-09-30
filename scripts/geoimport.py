#!/usr/bin/env python3
"""Manual data ingestion into PostGIS. Runs inside the geotools container.

Normally invoked through make (see `make help` and docs/setup/04-data-import.md):

  geoimport.py inspect <file> [--layer L]
  geoimport.py import  <file> <src_schema.table> [--layer L] [--srs EPSG:4326|native]
                       [--src-srs EPSG:xxxx] [--mode overwrite|append] [--fix] [--clip]
                       [--oo KEY=VALUE ...] [--license TEXT] [--notes TEXT]
  geoimport.py recipe  <name>          # run data/recipes/<name>.yaml
  geoimport.py all                     # run every enabled recipe
  geoimport.py list [--no-recipe]      # show app.datasets
  geoimport.py cog <file.tif>          # write a Cloud Optimized GeoTIFF to data/cog/
  geoimport.py sync                    # mirror data/recipes/*.yaml into app.recipes (+ key status)
  geoimport.py health [name]           # refresh outputs/footprints and run live health checks
  geoimport.py freshness [name]        # compare loaded data with what upstream offers now

Every import, recipe and cog command is recorded in app.jobs/app.runs (admin dashboard).

<file> is looked up in data/incoming/ (mounted at /data), then relative to the repo.
Zip files are read in place through /vsizip/.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shlex
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import psycopg
import yaml
from osgeo import gdal, ogr

from etl import freshness, health, registry, runs
from etl import outputs as outputs_mod
from etl.redact import redact

gdal.UseExceptions()

REPO = Path("/work")
INCOMING = Path("/data")
DOWNLOADS = REPO / "data" / "cache" / "downloads"
RECIPES = REPO / "data" / "recipes"
PROJECTS = REPO / "projects"
COG_DIR = REPO / "data" / "cog"

LOADER = "service=loader"
TARGET_RE = re.compile(r"^(src_[a-z][a-z0-9_]*)\.([a-z_][a-z0-9_]*)$")
CSV_XY = ["X_POSSIBLE_NAMES=lon*,long*,x", "Y_POSSIBLE_NAMES=lat*,y", "AUTODETECT_TYPE=YES"]
RECIPE_KEYS = {"name", "description", "source", "target", "srs", "src_srs", "mode",
               "fix_invalid", "clip_web_mercator", "open_options", "license", "notes", "enabled", "todo",
               # recipe format v2 (plan: admin-dashboard §3); Phase A reads the descriptive ones
               "kind", "group", "title", "agency", "attribution", "upstream", "vintage", "coverage", "parts",
               "requires_keys", "outputs", "steps", "depends_on", "freshness", "retention", "concurrency",
               "estimate", "rules", "where", "spat", "ogr_args", "analysis_srs", "resolution", "resampling", "nodata"}
DOWNLOADED_BYTES = 0


class ImportError_(Exception):
    """A user-facing failure: printed without a traceback."""


# --------------------------------------------------------------------------- sources

def download(url: str, filename: str | None = None) -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS / (filename or url.rstrip("/").rsplit("/", 1)[-1])
    if dest.exists() and dest.stat().st_size > 0:
        print(f"using cached download {dest.relative_to(REPO)}")
        return dest
    print(f"downloading {redact(url)}")
    global DOWNLOADED_BYTES
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "spatial-geoimport/1"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
        h = resp.headers
        markers = {"etag": h.get("ETag"), "last_modified": h.get("Last-Modified"),
                   "bytes": int(h["Content-Length"]) if h.get("Content-Length") else None}
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            DOWNLOADED_BYTES += len(chunk)
    tmp.rename(dest)
    markers = freshness.portal_item_markers(url) or markers
    # Upstream version markers, compared later by `geoimport.py freshness`.
    freshness.headers_sidecar(dest).write_text(json.dumps(markers))
    return dest


def resolve(path: str) -> Path:
    p = Path(path)
    for candidate in ([p] if p.is_absolute() else [INCOMING / p, REPO / p]):
        if candidate.exists():
            return candidate
    raise ImportError_(f"file not found: {path} (looked in data/incoming/ and the repo root)")


def esrijson_url(a: dict) -> str:
    """GDAL ESRIJSON source for an ArcGIS Feature/Map Server layer; GDAL pages through it (resultOffset)."""
    params = {"where": a.get("where", "1=1"), "outFields": a.get("out_fields", "*"),
              "outSR": "4326", "returnGeometry": "true", "f": "json"}
    if a.get("page_size"):  # some servers fail on large pages; GDAL keeps paging with resultOffset
        params.update(resultRecordCount=str(a["page_size"]), orderByFields=a.get("order_by", "OBJECTID"))
    params.update({k: str(v) for k, v in (a.get("params") or {}).items()})  # e.g. geometryPrecision
    q = urllib.parse.urlencode(params)
    return f"ESRIJSON:{a['url'].rstrip('/')}/query?{q}"


def fetch_arcgis(a: dict, target: str) -> Path:
    """Snapshot an ArcGIS layer to a local GeoPackage, then import that like any file.

    Streaming ESRIJSON straight into PostgreSQL mangles date fields (COPY receives truncated values);
    the snapshot also gives every run a checksummed, re-importable copy.
    """
    global DOWNLOADED_BYTES
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS / f"arcgis_{target.replace('.', '__')}.gpkg"
    tmp = dest.with_name(dest.stem + ".part.gpkg")
    tmp.unlink(missing_ok=True)
    print(f"fetching {redact(a['url'])} (where {a.get('where', '1=1')})", flush=True)
    if runs.run_cmd(["ogr2ogr", "-f", "GPKG", str(tmp), esrijson_url(a), "-nln", "features", "-progress"]) != 0:
        tmp.unlink(missing_ok=True)
        raise ImportError_("ArcGIS download failed (see log above)")
    tmp.replace(dest)
    DOWNLOADED_BYTES += dest.stat().st_size
    return dest


def gdal_path(p: Path) -> str:
    return f"/vsizip/{p}" if p.suffix.lower() == ".zip" else str(p)


def sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def is_csv(p: Path) -> bool:
    return p.suffix.lower() == ".csv"


def open_options_for(p: Path, oo: list[str]) -> list[str]:
    if is_csv(p) and not any(o.upper().startswith(("X_POSSIBLE", "Y_POSSIBLE")) for o in oo):
        return [*oo, *CSV_XY]
    return list(oo)


def open_vector(gpath: str, oo: list[str]):
    try:
        return gdal.OpenEx(gpath, gdal.OF_VECTOR, open_options=list(oo))
    except RuntimeError as e:
        raise ImportError_(f"GDAL could not open {gpath}: {e}") from None


def pick_layer(ds, name: str | None):
    if name:
        lyr = ds.GetLayerByName(name)
        if lyr is None:
            raise ImportError_(f"layer '{name}' not found; layers: {layer_names(ds)}")
        return lyr
    if ds.GetLayerCount() == 1:
        return ds.GetLayer(0)
    raise ImportError_(f"source has {ds.GetLayerCount()} layers, pass one with l=<layer>: {layer_names(ds)}")


def layer_names(ds) -> list[str]:
    return [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]


def srs_label(lyr) -> str | None:
    srs = lyr.GetSpatialRef()
    if srs is None:
        return None
    try:
        srs.AutoIdentifyEPSG()
    except RuntimeError:
        pass
    code = srs.GetAuthorityCode(None)
    auth = srs.GetAuthorityName(None)
    return f"{auth}:{code}" if code and auth else srs.GetName()


def geom_name(lyr) -> str:
    return ogr.GeometryTypeToName(ogr.GT_Flatten(lyr.GetGeomType()))


def is_point_layer(lyr) -> bool:
    return ogr.GT_Flatten(lyr.GetGeomType()) in (ogr.wkbPoint, ogr.wkbMultiPoint)


# --------------------------------------------------------------------------- inspect

def cmd_inspect(args) -> None:
    p = resolve(args.file)
    oo = open_options_for(p, args.oo)
    ds = open_vector(gdal_path(p), oo)
    print(f"file:   {p}\ndriver: {ds.GetDriver().ShortName}\nlayers: {ds.GetLayerCount()}")
    layers = [pick_layer(ds, args.layer)] if args.layer else [ds.GetLayer(i) for i in range(ds.GetLayerCount())]
    for lyr in layers:
        defn = lyr.GetLayerDefn()
        print(f"\n  layer:    {lyr.GetName()}")
        print(f"  features: {lyr.GetFeatureCount()}")
        print(f"  geometry: {geom_name(lyr)}")
        print(f"  srs:      {srs_label(lyr) or '(none - pass src_srs=EPSG:xxxx when importing)'}")
        ext = lyr.GetExtent(can_return_null=True)
        if ext:
            print(f"  extent:   {ext[0]:.6f}, {ext[2]:.6f}, {ext[1]:.6f}, {ext[3]:.6f}")
        print("  fields:")
        for i in range(defn.GetFieldCount()):
            fd = defn.GetFieldDefn(i)
            print(f"    {fd.GetName():<28} {fd.GetTypeName()}")


# --------------------------------------------------------------------------- import

def dependents(conn, schema: str, table: str) -> list[str]:
    """Views that depend on the target table (ogr2ogr -overwrite would DROP ... CASCADE them)."""
    rows = conn.execute(
        """
        SELECT DISTINCT v.relnamespace::regnamespace::text || '.' || v.relname
        FROM pg_depend d
        JOIN pg_rewrite r ON r.oid = d.objid
        JOIN pg_class v   ON v.oid = r.ev_class
        WHERE d.refobjid = to_regclass(%s) AND v.oid <> d.refobjid
        ORDER BY 1
        """,
        (f"{schema}.{table}",),
    ).fetchall()
    return [r[0] for r in rows]


def columns(conn, qualified: str) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT a.attname, format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute a
        WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum
        """,
        (qualified,),
    ).fetchall()
    return dict(rows)


def swap_in_stage(conn, schema: str, table: str, stage: str, deps: list[str]) -> None:
    target, staged = f"{schema}.{table}", f"{schema}.{stage}"
    tcols, scols = columns(conn, target), columns(conn, staged)
    if tcols != scols:
        conn.execute(f'DROP TABLE IF EXISTS "{schema}"."{stage}"')
        conn.commit()
        added = sorted(set(scols) - set(tcols))
        removed = sorted(set(tcols) - set(scols))
        changed = sorted(c for c in set(tcols) & set(scols) if tcols[c] != scols[c])
        raise ImportError_(
            f"{target} has dependent views {deps}, and the new data has a different structure "
            f"(added={added} removed={removed} changed={changed}).\n"
            "  To replace it anyway: drop those views (make psql), re-run the import, then `make seed`."
        )
    collist = ", ".join(f'"{c}"' for c in tcols)
    with conn.transaction():
        conn.execute(f'TRUNCATE "{schema}"."{table}"')
        conn.execute(f'INSERT INTO "{schema}"."{table}" ({collist}) SELECT {collist} FROM "{schema}"."{stage}"')
        conn.execute(f'DROP TABLE "{schema}"."{stage}"')
        conn.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE((SELECT max(id) FROM "
            f'"{schema}"."{table}"), 0) + 1, false) WHERE pg_get_serial_sequence(%s, \'id\') IS NOT NULL',
            (target, target),
        )
    print(f"replaced rows in {target} in place (kept dependent views: {', '.join(deps)})")


# Web Mercator (EPSG:3857) is undefined at the poles; older PROJ versions (e.g. 7.2 in the
# PostGIS image) raise "tolerance condition error" when tiPG transforms geometries reaching
# beyond this latitude (Antarctica at -90). clip_web_mercator trims stored geometries to it.
MERCATOR_LAT = 85.0511


def geom_expr(gtype: str, inner: str) -> str:
    """Wrap a geometry-producing SQL expression so the result keeps the column's type."""
    dim = 3 if "POLYGON" in gtype.upper() else 2 if "LINE" in gtype.upper() else 1
    expr = f"ST_CollectionExtract({inner}, {dim})"
    return f"ST_Multi({expr})" if gtype.upper().startswith("MULTI") else expr


def post_import(conn, schema: str, table: str, fix: bool, clip: bool = False) -> dict:
    gc = conn.execute(
        "SELECT type, srid FROM geometry_columns WHERE f_table_schema = %s AND f_table_name = %s AND f_geometry_column = 'geom'",
        (schema, table),
    ).fetchone()
    if gc is None:
        raise ImportError_(f"{schema}.{table} has no 'geom' geometry column registered; was the source non-spatial?")
    gtype, srid = gc
    q = f'"{schema}"."{table}"'
    count, invalid = conn.execute(
        f"SELECT count(*), count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) FROM {q}"
    ).fetchone()
    if invalid and fix:
        conn.execute(f"UPDATE {q} SET geom = {geom_expr(gtype, 'ST_MakeValid(geom)')} "
                     "WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)")
        print(f"fixed {invalid} invalid geometries with ST_MakeValid")
        invalid = conn.execute(f"SELECT count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)) FROM {q}").fetchone()[0]
    if clip:
        if srid != 4326:
            raise ImportError_(f"clip_web_mercator needs EPSG:4326 data, {schema}.{table} has SRID {srid}")
        env = f"ST_MakeEnvelope(-180, -{MERCATOR_LAT}, 180, {MERCATOR_LAT}, 4326)"
        cur = conn.execute(
            f"UPDATE {q} SET geom = {geom_expr(gtype, f'ST_Intersection(geom, {env})')} "
            f"WHERE geom IS NOT NULL AND (ST_YMin(geom) < -{MERCATOR_LAT} OR ST_YMax(geom) > {MERCATOR_LAT})"
        )
        if cur.rowcount:
            print(f"clipped {cur.rowcount} geometries to ±{MERCATOR_LAT}° latitude (Web Mercator limit)")
    conn.execute(f"ANALYZE {q}")
    conn.commit()
    return {"geometry_type": gtype, "srid": srid, "row_count": count, "invalid_geom_count": invalid}


def record(conn, schema, table, *, source, layer, digest, source_srs, target_srs, stats, recipe, license, notes):
    """Provenance of the imported table, as its postgis_table output in the dataset registry."""
    run_id = runs.ACTIVE.run_id if runs.ACTIVE else None
    conn.execute(
        """
        INSERT INTO app.dataset_outputs (recipe_name, kind, locator, source, source_layer, source_sha256,
            source_srs, target_srs, geometry_type, srid, row_count, invalid_geom_count,
            license, notes, checksum, loaded_run_id, imported_at, imported_by)
        VALUES (%s, 'postgis_table', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), current_user)
        ON CONFLICT (kind, locator) DO UPDATE SET
            recipe_name = EXCLUDED.recipe_name,
            source = EXCLUDED.source, source_layer = EXCLUDED.source_layer,
            source_sha256 = EXCLUDED.source_sha256, source_srs = EXCLUDED.source_srs,
            target_srs = EXCLUDED.target_srs, geometry_type = EXCLUDED.geometry_type,
            srid = EXCLUDED.srid, row_count = EXCLUDED.row_count,
            invalid_geom_count = EXCLUDED.invalid_geom_count,
            license = COALESCE(EXCLUDED.license, app.dataset_outputs.license),
            notes = COALESCE(EXCLUDED.notes, app.dataset_outputs.notes),
            checksum = EXCLUDED.checksum, loaded_run_id = EXCLUDED.loaded_run_id,
            imported_at = now(), imported_by = current_user
        """,
        (recipe, f"{schema}.{table}", redact(source), layer, digest, source_srs, target_srs,
         stats["geometry_type"], stats["srid"], stats["row_count"], stats["invalid_geom_count"],
         license, notes, digest, run_id),
    )
    conn.commit()


def do_import(*, target: str, path: str | None = None, url: str | None = None, layer: str | None = None,
              srs: str = "EPSG:4326", src_srs: str | None = None, mode: str = "overwrite", fix: bool = False, clip: bool = False,
              oo: list[str] | None = None, recipe: str | None = None, license: str | None = None,
              notes: str | None = None, arcgis: dict | None = None, filename: str | None = None,
              where: str | None = None, spat: list[float] | None = None, ogr_args: list[str] | None = None,
              inner: str | None = None) -> dict:
    m = TARGET_RE.match(target)
    if not m:
        raise ImportError_(f"target must be src_<domain>.<table> in lowercase, got '{target}'")
    schema, table = m.groups()
    if mode not in ("overwrite", "append"):
        raise ImportError_(f"mode must be overwrite or append, got '{mode}'")

    local = download(url, filename) if url else (fetch_arcgis(arcgis, target) if arcgis else resolve(path))
    oo = open_options_for(local, oo or [])
    if is_csv(local) and not src_srs:
        src_srs = "EPSG:4326"  # lon/lat CSVs carry no CRS; override with src_srs=
    gpath = gdal_path(local) + (f"/{inner}" if inner else "")  # inner: path inside an archive (e.g. a .gdb)
    ds = open_vector(gpath, oo)
    lyr = pick_layer(ds, layer)
    layer_name = lyr.GetName()
    source_srs = src_srs or srs_label(lyr)
    if source_srs is None and srs != "native":
        raise ImportError_("source has no CRS; pass src_srs=EPSG:xxxx (see make inspect)")
    point = is_point_layer(lyr)
    # A source field named "id" would collide with our generated key column (FID=id).
    # Load with a temporary key, then rename: source "id" -> "source_id", key -> "id".
    defn = lyr.GetLayerDefn()
    has_id_field = any(defn.GetFieldDefn(i).GetName().lower() == "id" for i in range(defn.GetFieldCount()))
    ds = None  # close before ogr2ogr opens it
    if has_id_field and mode == "append":
        raise ImportError_("the source has its own 'id' field, which append mode cannot map "
                           "(it was stored as 'source_id'). Rename the field in the source, or re-import with m=overwrite.")

    with psycopg.connect(LOADER) as conn:
        if not conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone():
            raise ImportError_(
                f"schema {schema} does not exist. Create it with a migration: "
                f"make migration n={schema}  (then: CALL app.ensure_src_schema('{schema}'); and make migrate)"
            )
        deps = dependents(conn, schema, table) if mode == "overwrite" else []

    load_table = f"_stage_{table}"[:63] if deps else table
    fid = "_geoimport_fid" if has_id_field else "id"
    cmd = ["ogr2ogr", "-f", "PostgreSQL", "-nln", f"{schema}.{load_table}"]
    for o in oo:
        cmd += ["-oo", o]
    cmd += [str(a) for a in ogr_args or []]  # recipe escape hatch, e.g. -fieldTypeToString Date
    if where:
        cmd += ["-where", where]
    if spat:
        cmd += ["-spat", *[str(v) for v in spat], "-spat_srs", "EPSG:4326"]
    if src_srs:
        cmd += ["-s_srs", src_srs]
    if srs != "native":
        cmd += ["-t_srs", srs]
    if not point:
        cmd += ["-nlt", "PROMOTE_TO_MULTI"]
    cmd += ["-lco", "GEOMETRY_NAME=geom", "-lco", f"FID={fid}", "-lco", "SPATIAL_INDEX=GIST",
            "-lco", "PRECISION=NO", "-lco", "LAUNDER=YES",
            "--config", "PG_USE_COPY", "YES", "-gt", "65536", "-progress",
            "-overwrite" if mode == "overwrite" else "-append",
            f"PG:{LOADER}", gpath, layer_name]
    print("$ " + redact(shlex.join(cmd)), flush=True)
    returncode = runs.run_cmd(cmd)
    if returncode != 0:
        if deps:
            with psycopg.connect(LOADER) as conn:
                conn.execute(f'DROP TABLE IF EXISTS "{schema}"."{load_table}"')
        raise ImportError_(f"ogr2ogr failed with exit code {returncode}"
                           + (f" ({schema}.{table} and its views are unchanged)" if deps else ""))

    with psycopg.connect(LOADER) as conn:
        if has_id_field:
            q = f'"{schema}"."{load_table}"'
            conn.execute(f'ALTER TABLE {q} RENAME COLUMN "id" TO "source_id"')
            conn.execute(f'ALTER TABLE {q} RENAME COLUMN "{fid}" TO "id"')
            conn.commit()
            print("source field 'id' stored as 'source_id'; 'id' is the generated key")
        if deps:
            swap_in_stage(conn, schema, table, load_table, deps)
        stats = post_import(conn, schema, table, fix, clip)
        digest = sha256(local)
        record(conn, schema, table, source=url or (arcgis or {}).get("url") or str(path), layer=layer_name, digest=digest,
               source_srs=source_srs, target_srs=srs, stats=stats, recipe=recipe,
               license=license, notes=notes)
        if recipe and url:
            freshness.record_loaded_part(conn, recipe, local, runs.ACTIVE.run_id if runs.ACTIVE else None,
                                         digest, stats["row_count"])
            conn.commit()
        elif recipe and arcgis:
            freshness.record_arcgis_part(conn, recipe, arcgis["url"], runs.ACTIVE.run_id if runs.ACTIVE else None,
                                         stats["row_count"])
            conn.commit()

    print(f"OK {schema}.{table}: {stats['row_count']} rows, {stats['geometry_type']}, SRID {stats['srid']}"
          + (f", {stats['invalid_geom_count']} INVALID geometries (re-run with fix=1)" if stats["invalid_geom_count"] else ""))
    return stats


def finalize(recipe: str | None) -> None:
    """After an import: refresh outputs, footprints, coverage and health for the dashboard."""
    with psycopg.connect(LOADER) as conn:
        touched = outputs_mod.refresh_outputs(conn, recipe, PROJECTS)
        for name in touched or [recipe]:
            health.check_outputs(conn, name)


def cmd_import(args) -> None:
    sync_quietly()
    with runs.RunRecorder("import", params={"file": args.file, "target": args.target}) as run:
        stats = do_import(target=args.target, path=args.file, layer=args.layer, srs=args.srs, src_srs=args.src_srs,
                          mode=args.mode, fix=args.fix, clip=args.clip, oo=args.oo, license=args.license,
                          notes=args.notes)
        run.rows, run.bytes = stats["row_count"], DOWNLOADED_BYTES
        finalize(None)
    stub = {
        "name": args.target.split(".", 1)[1],
        "source": {"path": args.file, **({"layer": args.layer} if args.layer else {})},
        "target": args.target, "srs": args.srs, "mode": args.mode,
        **({"src_srs": args.src_srs} if args.src_srs else {}),
        **({"fix_invalid": True} if args.fix else {}),
        **({"clip_web_mercator": True} if args.clip else {}),
        **({"open_options": args.oo} if args.oo else {}),
        "license": args.license or "TODO", "notes": args.notes or "TODO", "enabled": True,
    }
    print("\nThis import has no recipe, so `make reset-db` would lose it. To keep it, save as "
          f"data/recipes/{stub['name']}.yaml:\n---")
    print(yaml.safe_dump(stub, sort_keys=False).rstrip())


# --------------------------------------------------------------------------- recipes

def load_recipe(name: str) -> dict:
    path = RECIPES / f"{name}.yaml"
    if not path.exists():
        raise ImportError_(f"no recipe {path.relative_to(REPO)}; available: {[p.stem for p in sorted(RECIPES.glob('*.yaml'))]}")
    r = yaml.safe_load(path.read_text())
    unknown = set(r) - RECIPE_KEYS
    if unknown:
        raise ImportError_(f"{path.name}: unknown keys {sorted(unknown)}")
    if r.get("name") != name:
        raise ImportError_(f"{path.name}: 'name' must equal the file name ({name})")
    src = r.get("source") or {}
    if sum(bool(src.get(k)) for k in ("url", "path", "arcgis")) != 1:
        raise ImportError_(f"{path.name}: source needs exactly one of url, path or arcgis")
    if "target" not in r:
        raise ImportError_(f"{path.name}: missing target")
    return r


def run_recipe(r: dict) -> dict:
    src = r["source"]
    print(f"\n=== recipe {r['name']} -> {r['target']}")
    return do_import(target=r["target"], path=src.get("path"), url=src.get("url"), layer=src.get("layer"),
                     arcgis=src.get("arcgis"), filename=src.get("filename"), where=r.get("where"), spat=r.get("spat"), ogr_args=r.get("ogr_args"), inner=src.get("inner"),
                     srs=r.get("srs", "EPSG:4326"), src_srs=r.get("src_srs"), mode=r.get("mode", "overwrite"),
                     fix=bool(r.get("fix_invalid")), clip=bool(r.get("clip_web_mercator")), oo=r.get("open_options") or [], recipe=r["name"],
                     license=r.get("license"), notes=r.get("notes"))


def run_recorded(r: dict, params: dict | None = None) -> dict:
    """One recipe = one recorded run (CLI and, later, the worker use this same path)."""
    global DOWNLOADED_BYTES
    DOWNLOADED_BYTES = 0
    with runs.RunRecorder("import", recipe=r["name"], params=params or {},
                          concurrency=r.get("concurrency", "network")) as run:
        missing = registry.missing_keys(r)
        if missing:
            raise ImportError_(f"recipe {r['name']} requires {', '.join(missing)}, which is not configured. "
                               "Add it to .env (see .env.example) and run the command again.")
        stats = run_raster_recipe(r) if r.get("kind") == "raster" else run_recipe(r)
        run.rows, run.bytes = stats.get("row_count"), DOWNLOADED_BYTES
        run.outcome = "downloaded" if DOWNLOADED_BYTES else "imported from cached download"
        finalize(r["name"])
    return stats


COG_NAME = re.compile(r"^[a-z0-9_/-]+$")


def run_raster_recipe(r: dict) -> dict:
    """kind: raster -> download, clip + reproject, validated COG in data/cog/, swapped in atomically.

    The previous version is kept in data/cog/.versions/<name>/ (retention.keep_versions, default 1), a
    provenance sidecar <name>.json is written next to the COG, and the COG + its titiler tile URL are
    registered as dataset outputs (health-checked by `make health-datasets`).
    """
    src, target = r["source"], r["target"]
    name = target[4:] if target.startswith("cog:") else ""
    if not COG_NAME.match(name):
        raise ImportError_(f"raster target must be cog:<lowercase/path>, got '{target}'")
    print(f"\n=== recipe {r['name']} -> data/cog/{name}.tif")
    local = download(src["url"], src.get("filename")) if src.get("url") else resolve(src["path"])
    gsrc = gdal_path(local) + (f"/{src['inner']}" if src.get("inner") else "")
    dest = COG_DIR / f"{name}.tif"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.stem}.tmp.tif")
    tmp.unlink(missing_ok=True)
    res = str(r.get("resolution", 100))
    cmd = ["gdalwarp", "-overwrite", "-t_srs", r.get("srs", "EPSG:26919"), "-tr", res, res,
           "-r", r.get("resampling", "bilinear"), "-dstnodata", str(r.get("nodata", -9999))]
    if r.get("spat"):
        cmd += ["-te_srs", "EPSG:4326", "-te", *[str(v) for v in r["spat"]]]
    cmd += ["-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "OVERVIEWS=AUTO", "-co", "BLOCKSIZE=512", gsrc, str(tmp)]
    print("$ " + redact(shlex.join(cmd)), flush=True)
    if runs.run_cmd(cmd) != 0:
        tmp.unlink(missing_ok=True)
        raise ImportError_("gdalwarp failed")

    # Validate before swapping in: COG layout, CRS, and at least some valid pixels.
    gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")  # no .aux.xml side files
    info = gdal.Info(str(tmp), format="json")
    ds = gdal.Open(str(tmp))
    band = ds.GetRasterBand(1)
    try:
        mn, mx, mean, _std = band.ComputeStatistics(False)
    except RuntimeError:
        mn = mx = mean = None
    layout = (info.get("metadata", {}).get("IMAGE_STRUCTURE", {}) or {}).get("LAYOUT")
    epsg = ds.GetSpatialRef().GetAuthorityCode(None) if ds.GetSpatialRef() else None
    gt = ds.GetGeoTransform()
    raster = {"width": ds.RasterXSize, "height": ds.RasterYSize, "bands": ds.RasterCount,
              "dtype": gdal.GetDataTypeName(band.DataType), "resolution": [gt[1], -gt[5]],
              "crs": f"EPSG:{epsg}" if epsg else None, "nodata": band.GetNoDataValue(),
              "min": mn, "max": mx, "mean": mean}
    ds = None
    if layout != "COG":
        tmp.unlink(missing_ok=True)
        raise ImportError_(f"output is not a valid COG (layout {layout})")
    if mn is None:
        tmp.unlink(missing_ok=True)
        raise ImportError_("output has no valid pixels (check spat / source CRS)")

    if dest.exists():
        vdir = COG_DIR / ".versions" / name
        vdir.mkdir(parents=True, exist_ok=True)
        dest.replace(vdir / f"{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}.tif")
        keep = int((r.get("retention") or {}).get("keep_versions", 1))
        for old in sorted(vdir.glob("*.tif"))[:-keep] if keep else sorted(vdir.glob("*.tif")):
            old.unlink()
    tmp.replace(dest)
    digest, src_digest = sha256(dest), sha256(local)
    dest.with_suffix(".json").write_text(json.dumps({
        "recipe": r["name"], "source": src.get("url") or src.get("path"), "source_sha256": src_digest,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "params": {k: r.get(k) for k in ("srs", "resolution", "resampling", "spat", "nodata")},
        "raster": raster, "sha256": digest, "license": r.get("license"), "attribution": r.get("attribution"),
    }, indent=2))

    run_id = runs.ACTIVE.run_id if runs.ACTIVE else None
    with psycopg.connect(LOADER) as conn:
        outputs_mod.record_cog(conn, r["name"], name, raster, dest.stat().st_size, digest,
                               json.dumps(info.get("wgs84Extent")), run_id, PROJECTS)
        if src.get("url"):
            freshness.record_loaded_part(conn, r["name"], local, run_id, src_digest, None)
        conn.commit()
    print(f"OK data/cog/{name}.tif: {raster['width']}x{raster['height']} {raster['dtype']}, {raster['crs']}, "
          f"{raster['resolution'][0]:g} m, values {mn:.2f} .. {mx:.2f}")
    return {"row_count": None, "raster": raster}


def cmd_recipe(args) -> None:
    sync_quietly()
    r = load_recipe(args.name)
    if r.get("enabled") is False and not args.force:
        raise ImportError_(f"recipe {args.name} is disabled (todo: {r.get('todo', '-')}). "
                           "Set enabled: true, or run with force=1.")
    run_recorded(r, {"force": bool(args.force)})


def cmd_all(args) -> None:
    sync_quietly()
    names = [p.stem for p in sorted(RECIPES.glob("*.yaml"))]
    failed, skipped = [], []
    for name in names:
        try:
            r = load_recipe(name)
            if r.get("enabled") is False:
                skipped.append(f"{name} (todo: {r.get('todo', '-')})")
                continue
            if r.get("kind") == "raster" and not getattr(args, "rasters", False):
                skipped.append(f"{name} (raster: COGs survive reset-db; rebuild with make import-all rasters=1)")
                continue
            run_recorded(r, {"via": "import-all"})
        except (ImportError_, OSError, RuntimeError, psycopg.Error) as e:
            print(f"FAILED {name}: {e}", file=sys.stderr)
            failed.append(name)
    print(f"\nrecipes: {len(names) - len(failed) - len(skipped)} imported, {len(skipped)} disabled, {len(failed)} failed")
    for s in skipped:
        print(f"  disabled: {s}")
    if failed:
        raise ImportError_(f"failed recipes: {failed}")


# --------------------------------------------------------------------------- list / cog

def cmd_list(args) -> None:
    sync_quietly()
    with psycopg.connect(LOADER) as conn:
        where = "WHERE recipe IS NULL" if args.no_recipe else ""
        rows = conn.execute(
            f"""SELECT table_schema || '.' || table_name, row_count, geometry_type, srid,
                       COALESCE(recipe, '-- none --'), source_srs,
                       to_char(imported_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
                FROM app.datasets {where} ORDER BY 1"""
        ).fetchall()
        untracked = conn.execute(
            """SELECT t.table_schema || '.' || t.table_name FROM information_schema.tables t
               WHERE t.table_schema LIKE 'src\\_%%' AND t.table_type = 'BASE TABLE'
                 AND NOT EXISTS (SELECT 1 FROM app.datasets d
                                 WHERE d.table_schema = t.table_schema AND d.table_name = t.table_name)
               ORDER BY 1"""
        ).fetchall()
    if args.no_recipe:
        for r in rows:
            print(r[0])
        for r in untracked:
            print(f"{r[0]} (not in app.datasets)")
        return
    header = ("table", "rows", "geometry", "srid", "recipe", "source srs", "imported (UTC)")
    widths = [max(len(str(x)) for x in col) for col in zip(header, *rows)] if rows else [len(h) for h in header]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*header))
    for r in rows:
        print(fmt.format(*[str(x) for x in r]))
    if untracked:
        print("\ntables in src_* without provenance (created outside make import):")
        for r in untracked:
            print(f"  {r[0]}")


def cmd_cog(args) -> None:
    src = resolve(args.file)
    COG_DIR.mkdir(parents=True, exist_ok=True)
    dest = COG_DIR / f"{src.stem}.tif"
    cmd = ["gdal_translate", "-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "OVERVIEWS=AUTO",
           "-co", "BLOCKSIZE=512", gdal_path(src), str(dest)]
    with runs.RunRecorder("derive", params={"op": "cog", "file": args.file}) as run:
        print("$ " + redact(shlex.join(cmd)), flush=True)
        if runs.run_cmd(cmd) != 0:
            raise ImportError_("gdal_translate failed")
        run.outcome = f"wrote {dest.relative_to(REPO)}"
        print(f"OK wrote {dest.relative_to(REPO)}")


# --------------------------------------------------------------------------- registry commands

def sync_quietly() -> None:
    """Mirror recipes before every command, so the dashboard and history always match the YAML."""
    with psycopg.connect(LOADER) as conn:
        result = registry.sync_recipes(conn, RECIPES)
    for name, err in result["errors"].items():
        print(f"warning: recipe {name}.yaml could not be synced: {err}", file=sys.stderr)


def cmd_sync(_args) -> None:
    with psycopg.connect(LOADER) as conn:
        result = registry.sync_recipes(conn, RECIPES)
    print(f"synced {result['synced']} recipes"
          + (f"; orphaned (YAML removed): {result['orphaned']}" if result["orphaned"] else "")
          + (f"; errors: {result['errors']}" if result["errors"] else ""))


def cmd_health(args) -> None:
    sync_quietly()
    with psycopg.connect(LOADER) as conn:
        outputs_mod.refresh_outputs(conn, args.name, PROJECTS)
        results = health.check_outputs(conn, args.name)
    for kind, locator, state, detail in results:
        print(f"{state.upper():<8}{kind:<17}{locator:<45}{detail}")
    if any(r[2] == "fail" for r in results):
        raise ImportError_("some outputs failed their health check")


def cmd_freshness(args) -> None:
    sync_quietly()
    with psycopg.connect(LOADER) as conn:
        results = freshness.check(conn, args.name, DOWNLOADS)
    for name, verdict, detail in results:
        print(f"{verdict.upper():<9}{name:<24}{detail}")


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="geoimport", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("inspect")
    p.add_argument("file")
    p.add_argument("--layer")
    p.add_argument("--oo", action="append", default=[])
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("import")
    p.add_argument("file")
    p.add_argument("target")
    p.add_argument("--layer")
    p.add_argument("--srs", default="EPSG:4326")
    p.add_argument("--src-srs")
    p.add_argument("--mode", default="overwrite", choices=["overwrite", "append"])
    p.add_argument("--fix", action="store_true")
    p.add_argument("--clip", action="store_true", help="clip to ±85.0511° (Web Mercator)")
    p.add_argument("--oo", action="append", default=[])
    p.add_argument("--license")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("recipe")
    p.add_argument("name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_recipe)

    p = sub.add_parser("all")
    p.add_argument("--rasters", action="store_true", help="also rebuild kind: raster recipes")
    p.set_defaults(func=cmd_all)

    p = sub.add_parser("list")
    p.add_argument("--no-recipe", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("cog")
    p.add_argument("file")
    p.set_defaults(func=cmd_cog)

    sub.add_parser("sync").set_defaults(func=cmd_sync)
    p = sub.add_parser("health")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_health)
    p = sub.add_parser("freshness")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_freshness)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except ImportError_ as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as e:
        print(f"ERROR: cannot connect to PostGIS as loader: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:  # GDAL/OGR errors (gdal.UseExceptions)
        print(f"ERROR: GDAL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
