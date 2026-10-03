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
import math
import os
import re
import shlex
import signal
import sys
import time
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
               "estimate", "rules", "where", "spat", "ogr_args", "analysis_srs", "resolution", "resampling", "nodata",
               "cutline_sql", "cog_options"}
DOWNLOADED_BYTES = 0
REDOWNLOAD = False  # recipe --redownload: ignore cached downloads


class ImportError_(Exception):
    """A user-facing failure: printed without a traceback."""


# --------------------------------------------------------------------------- sources

def download(url: str, filename: str | None = None) -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS / (filename or url.rstrip("/").rsplit("/", 1)[-1])
    if dest.exists() and dest.stat().st_size > 0 and not REDOWNLOAD:
        print(f"using cached download {dest.relative_to(REPO)}")
        return dest
    print(f"downloading {redact(url)}")
    global DOWNLOADED_BYTES
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "spatial-geoimport/1"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
            h = resp.headers
            markers = {"etag": h.get("ETag"), "last_modified": h.get("Last-Modified"),
                       "bytes": int(h["Content-Length"]) if h.get("Content-Length") else None}
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                DOWNLOADED_BYTES += len(chunk)
    except BaseException:  # failed or cancelled: never leave a partial file behind (the cached copy is untouched)
        tmp.unlink(missing_ok=True)
        raise
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
    try:
        if a.get("by_ids"):
            fetch_arcgis_by_ids(a, tmp)
            rc = 0
        else:
            rc = runs.run_cmd(["ogr2ogr", "-f", "GPKG", str(tmp), esrijson_url(a), "-nln", "features", "-progress"])
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if rc != 0:
        tmp.unlink(missing_ok=True)
        raise ImportError_("ArcGIS download failed (see log above)")
    tmp.replace(dest)
    DOWNLOADED_BYTES += dest.stat().st_size
    return dest


def _arcgis_post(url: str, params: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                 headers={"User-Agent": "spatial-geoimport/1", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read()
    global DOWNLOADED_BYTES
    DOWNLOADED_BYTES += len(body)
    d = json.loads(body)
    if "error" in d:
        raise ValueError(f"server error: {json.dumps(d['error'])[:200]}")
    return d


def fetch_arcgis_by_ids(a: dict, out: Path) -> None:
    """arcgis.by_ids: for large or flaky services (FEMA NFHL). Ask for every object ID first, then fetch the features
    in chunks of `page_size` IDs; each chunk is retried with backoff and split in half if it keeps failing, so one
    bad page (a timeout on heavy geometry) no longer aborts the whole download. Chunks are appended to `out`."""
    import tempfile
    query = a["url"].rstrip("/") + "/query"
    extra = {k: str(v) for k, v in (a.get("params") or {}).items()}
    ids = _arcgis_post(query, {"where": a.get("where", "1=1"), "returnIdsOnly": "true", "f": "json", **extra}).get("objectIds") or []
    ids.sort()
    if not ids:
        raise ImportError_("ArcGIS layer returned no object IDs for this filter")
    size = int(a.get("page_size", 500))
    print(f"{len(ids)} features in {math.ceil(len(ids) / size)} chunks of {size}", flush=True)
    base = {"outFields": a.get("out_fields", "*"), "outSR": "4326", "returnGeometry": "true", "f": "json", **extra}
    pending = [ids[i:i + size] for i in range(0, len(ids), size)]
    done, skipped = 0, []
    with tempfile.TemporaryDirectory(dir=DOWNLOADS) as td:
        while pending:
            chunk = pending.pop(0)
            tries = 4 if len(chunk) == size else 2  # a chunk that was already split: bisect faster
            d = None
            for attempt in range(tries):
                try:
                    d = _arcgis_post(query, {**base, "objectIds": ",".join(map(str, chunk))})
                    if "features" not in d or "fields" not in d:
                        raise ValueError("response without features/fields")
                    break
                except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
                    d = None
                    wait = 5 * 2 ** attempt
                    print(f"  chunk of {len(chunk)} failed ({e}); retry in {wait}s", flush=True)
                    time.sleep(wait)
            if d is None and len(chunk) == 1:
                # One feature the server cannot return (typically a huge geometry): ask for a ~1 m generalized
                # version, and skip it (recorded in the log) only if that fails too.
                try:
                    d = _arcgis_post(query, {**base, "objectIds": str(chunk[0]), "maxAllowableOffset": "0.00001"})
                    print(f"  feature {chunk[0]}: fetched with ~1 m generalization", flush=True)
                except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
                    print(f"  feature {chunk[0]}: SKIPPED, the server cannot return it ({e})", flush=True)
                    skipped.append(chunk[0])
                    continue
            if d is None:
                half = len(chunk) // 2  # keeps failing: smaller requests
                pending[:0] = [chunk[:half], chunk[half:]]
                continue
            page = Path(td) / "page.json"
            page.write_text(json.dumps(d))
            cmd = ["ogr2ogr", "-f", "GPKG", "--config", "OGR_ORGANIZE_POLYGONS", "ONLY_CCW", "-nln", "features",
                   *(["-append"] if out.exists() else []), str(out), f"ESRIJSON:{page}"]
            if runs.run_cmd(cmd) != 0:
                raise ImportError_("ogr2ogr could not append an ArcGIS chunk (see log above)")
            done += len(chunk)
            print(f"  {done}/{len(ids)}", flush=True)
    if skipped:
        print(f"WARNING: {len(skipped)} feature(s) skipped, object IDs {skipped[:20]}", flush=True)
        if len(skipped) > max(5, len(ids) // 1000):
            raise ImportError_(f"{len(skipped)} features could not be fetched; the service may be down")


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

SOURCE_KINDS = ("url", "path", "arcgis", "census_api", "sda", "tiles", "derive", "overture", "landfire", "ssurgo", "rasterize", "geoparquet", "cdl")
SSURGO_AREAS = re.compile(r"[A-Z]{2}[0-9]{0,3}%?")


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
    if sum(bool(src.get(k)) for k in SOURCE_KINDS) != 1:
        raise ImportError_(f"{path.name}: source needs exactly one of {', '.join(SOURCE_KINDS)}")
    for k in ("tiles", "rasterize", "cdl"):
        if src.get(k) and r.get("kind") != "raster":
            raise ImportError_(f"{path.name}: source.{k} needs kind: raster")
    for k in ("census_api", "sda"):
        if src.get(k) and r.get("kind") != "table":
            raise ImportError_(f"{path.name}: source.{k} needs kind: table")
    if src.get("ssurgo") and not SSURGO_AREAS.fullmatch(src["ssurgo"].get("areas", "")):
        raise ImportError_(f"{path.name}: source.ssurgo.areas must be a survey area pattern such as ME% or ME011")
    if "target" not in r:
        raise ImportError_(f"{path.name}: missing target")
    return r


def derived_cog(src: dict) -> Path:
    """The COG a derived recipe is made from (source.derive.from = a COG name such as maine/dem_30m)."""
    name = src["derive"]["from"]
    base = COG_DIR / f"{name}.tif"
    if not COG_NAME.match(name) or not base.is_file():
        raise ImportError_(f"source.derive.from: data/cog/{name}.tif does not exist; import the recipe that builds it first")
    return base


OVERTURE_STAC = "https://stac.overturemaps.org/catalog.json"
OVERTURE_S3 = "s3://overturemaps-us-west-2/release/{release}/theme={theme}/type={type}/*"


def fetch_overture(r: dict) -> tuple[Path, str]:
    """source.overture: one Overture Maps theme/type for an area, read straight from the public GeoParquet on S3 with
    DuckDB (only row groups whose bbox overlaps the area are fetched), clipped to `clip_sql`, written to a GeoPackage.

    overture: {release: latest, theme: places, type: place, columns: {name: names.primary, ...}, where: "...",
               clip_sql: "SELECT ST_AsText(...) FROM ..."}   (clip_sql returns one WKT polygon in EPSG:4326)
    """
    o = r["source"]["overture"]
    release = o.get("release", "latest")
    if release == "latest":
        with urllib.request.urlopen(OVERTURE_STAC, timeout=60) as resp:
            release = json.load(resp)["latest"]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release) or not all(re.fullmatch(r"[a-z_]+", o[k]) for k in ("theme", "type")):
        raise ImportError_(f"overture: bad release/theme/type {release!r} {o.get('theme')!r} {o.get('type')!r}")
    cols = o.get("columns") or {}
    if not all(IDENT.match(k) for k in cols):
        raise ImportError_("overture.columns: output names must be lowercase identifiers")
    with psycopg.connect(LOADER) as conn:
        wkt = conn.execute(o["clip_sql"]).fetchone()[0]
        xmin, ymin, xmax, ymax = conn.execute(
            "SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g) FROM ST_GeomFromText(%s) g", (wkt,)).fetchone()
    out = DOWNLOADS / f"overture_{r['name']}_{release}.gpkg"
    if out.exists() and not REDOWNLOAD:
        print(f"using cached Overture snapshot {out.relative_to(REPO)} (release {release})")
        return out, release
    select = ", ".join(["id"] + [f"{expr} AS {name}" for name, expr in cols.items()] + ["geometry"])
    print(f"overture {o['theme']}/{o['type']} release {release}, bbox {xmin:.3f},{ymin:.3f},{xmax:.3f},{ymax:.3f}", flush=True)
    geoparquet_to_gpkg(out, OVERTURE_S3.format(release=release, theme=o["theme"], type=o["type"]), select,
                       o.get("where"), wkt, (xmin, ymin, xmax, ymax))
    for old in DOWNLOADS.glob(f"overture_{r['name']}_*.gpkg"):  # keep only the release just fetched
        if old != out:
            old.unlink()
    return out, release


def geoparquet_to_gpkg(out: Path, url: str, select: str, where: str | None, wkt: str, box: tuple,
                       url_style: str | None = None) -> None:
    """DuckDB: GeoParquet on S3 -> GeoPackage layer 'features', only rows inside `wkt` (EPSG:4326). Files with a
    bbox struct column (Overture, the HIFLD archive) are pruned by row group before any geometry is read."""
    import duckdb
    xmin, ymin, xmax, ymax = box
    tmp = out.with_name(out.stem + ".part.gpkg")
    tmp.unlink(missing_ok=True)
    sql = (f"COPY (SELECT {select} FROM read_parquet('{url}', hive_partitioning=1) "
           f"WHERE bbox.xmin <= {xmax} AND bbox.xmax >= {xmin} AND bbox.ymin <= {ymax} AND bbox.ymax >= {ymin}"
           + (f" AND ({where})" if where else "") +
           f" AND ST_Intersects(geometry, ST_GeomFromText('{wkt}'))) "
           f"TO '{tmp}' WITH (FORMAT GDAL, DRIVER 'GPKG', LAYER_NAME 'features', SRS 'EPSG:4326')")
    con = duckdb.connect()
    try:
        con.execute(f"SET extension_directory='{DOWNLOADS.parent / 'duckdb'}'")
        for ext in ("spatial", "httpfs"):
            con.execute(f"INSTALL {ext}")
            con.execute(f"LOAD {ext}")
        con.execute("SET s3_region='us-west-2'")
        if url_style:  # 'path' for buckets with dots in their name (TLS fails on virtual-host URLs)
            con.execute(f"SET s3_url_style='{url_style}'")
        con.execute(sql)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    tmp.replace(out)


def fetch_geoparquet(r: dict) -> Path:
    """source.geoparquet: any GeoParquet dataset with a bbox column on S3 (e.g. the HIFLD archive on Source
    Cooperative), clipped to `clip_sql` like Overture.

    geoparquet: {url: "s3://bucket/path/*.parquet", s3_url_style: path, where: "...",
                 columns: {out_name: expr, ...} (default: every column), clip_sql: "SELECT ST_AsText(...)"}
    """
    g = r["source"]["geoparquet"]
    if not re.fullmatch(r"s3://[A-Za-z0-9._/*=-]+", g["url"]):
        raise ImportError_(f"geoparquet.url must be an s3:// path, got {g['url']!r}")
    cols = g.get("columns")
    if cols and not all(IDENT.match(k) for k in cols):
        raise ImportError_("geoparquet.columns: output names must be lowercase identifiers")
    with psycopg.connect(LOADER) as conn:
        wkt = conn.execute(g["clip_sql"]).fetchone()[0]
        box = conn.execute("SELECT ST_XMin(g), ST_YMin(g), ST_XMax(g), ST_YMax(g) FROM ST_GeomFromText(%s) g", (wkt,)).fetchone()
    out = DOWNLOADS / f"geoparquet_{r['name']}.gpkg"
    if out.exists() and not REDOWNLOAD:
        print(f"using cached GeoParquet extract {out.relative_to(REPO)}")
        return out
    select = (", ".join([f"{expr} AS {name}" for name, expr in cols.items()] + ["geometry"]) if cols
              else "* EXCLUDE (bbox)")
    print(f"geoparquet {g['url']}, bbox {box[0]:.3f},{box[1]:.3f},{box[2]:.3f},{box[3]:.3f}", flush=True)
    geoparquet_to_gpkg(out, g["url"], select, g.get("where"), wkt, box, g.get("s3_url_style"))
    return out


LFPS = "https://lfps.usgs.gov/api"


def fetch_landfire(r: dict) -> Path:
    """source.landfire: one LANDFIRE layer for the recipe's `spat` box from the LANDFIRE Product Service (an
    asynchronous job: submit, poll, download a zip). LFPS requires an email address (LANDFIRE_EMAIL in .env).

    landfire: {layer: LF2025_EVT, resolution: 30, projection: 26919}
    """
    lf = r["source"]["landfire"]
    layer = lf["layer"]
    if not re.fullmatch(r"LF\d{4}_[A-Z0-9_]+", layer):
        raise ImportError_(f"landfire.layer {layer!r} does not look like a LANDFIRE layer (e.g. LF2025_EVT)")
    out = DOWNLOADS / f"landfire_{layer}_{r['name']}.zip"
    if out.exists() and not REDOWNLOAD:
        print(f"using cached LANDFIRE download {out.relative_to(REPO)}")
        return out
    email = os.environ.get("LANDFIRE_EMAIL", "")
    if not email:
        raise ImportError_("LANDFIRE_EMAIL is not set: the LANDFIRE Product Service requires an email address per job")
    # New LANDFIRE versions are released region by region; an unreleased region comes back as all nodata.
    with urllib.request.urlopen(f"{LFPS}/products", timeout=60) as resp:
        products = json.dumps(json.load(resp))
    m = re.search(r'\{[^{}]*"layerName": "' + layer + r'"[^{}]*\}', products)
    if not m:
        raise ImportError_(f"LANDFIRE does not offer {layer}; see {LFPS}/products")
    areas = json.loads(m.group(0)).get("geoAreas", "")
    if areas != "All":
        print(f"WARNING: {layer} covers only {areas or 'unknown areas'} so far; outside them the output is empty "
              "(use the previous version, e.g. LF2024_*)", flush=True)
    xmin, ymin, xmax, ymax = r["spat"]
    body = {"Layer_List": layer, "Area_of_Interest": f"{xmin} {ymin} {xmax} {ymax}",
            "Output_Projection": str(lf.get("projection", 26919)), "Resample_Resolution": int(lf.get("resolution", 30)),
            "Email": email}
    req = urllib.request.Request(f"{LFPS}/job/submit", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "spatial-geoimport/1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        submitted = json.load(resp)
    job = submitted.get("jobId")
    if not job:
        raise ImportError_(f"LANDFIRE job was not accepted: {redact(json.dumps(submitted))[:300]}")
    print(f"LANDFIRE job {job} submitted ({layer})", flush=True)
    deadline, last = time.monotonic() + 2 * 3600, None
    try:
        while True:
            time.sleep(15)
            with urllib.request.urlopen(f"{LFPS}/job/status?JobId={urllib.parse.quote(job)}", timeout=60) as resp:
                st = json.load(resp)
            state = st.get("status")
            if state != last:
                print(f"LANDFIRE job {job}: {state}" + (f" (queue {st['queuePosition']})" if st.get("queuePosition") else ""), flush=True)
                last = state
            if state == "Succeeded" and st.get("outputFile"):
                break
            if state in ("Failed", "Canceled"):
                raise ImportError_(f"LANDFIRE job {state.lower()}: {' | '.join(str(m) for m in (st.get('messages') or []))[-300:]}")
            if time.monotonic() > deadline:
                raise ImportError_("LANDFIRE job did not finish within 2 hours")
    except BaseException:
        if last not in ("Succeeded", "Failed", "Canceled"):  # cancelled here, or gave up: cancel it upstream too
            try:
                urllib.request.urlopen(f"{LFPS}/job/cancel?JobId={urllib.parse.quote(job)}", timeout=30).read()
            except Exception:  # noqa: BLE001
                pass
        raise
    download(st["outputFile"], out.name + ".download").replace(out)
    ds = gdal.Open(landfire_raster(out))
    band = ds.GetRasterBand(1)
    try:
        band.ComputeStatistics(True)  # approximate: an overview is enough to tell empty from not
        valid = float(band.GetMetadataItem("STATISTICS_VALID_PERCENT") or 0)
    except RuntimeError:  # "no valid pixels found in sampling"
        valid = 0.0
    band = ds = None
    if valid == 0:  # don't cache an empty download
        out.unlink(missing_ok=True)
        raise ImportError_(f"LANDFIRE returned only nodata for {layer} in this area (version not released here yet?)")
    return out


CDL_SERVICE = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLFile"


def fetch_cdl(r: dict) -> Path:
    """source.cdl: the USDA NASS Cropland Data Layer for one state and year from CropScape (GetCDLFile returns the
    URL of a prepared per-state GeoTIFF, which keeps NASS's colour table and class names).

    cdl: {year: 2025, fips: "23"}
    """
    c = r["source"]["cdl"]
    year, fips = int(c["year"]), str(c["fips"])
    if not re.fullmatch(r"\d{2}", fips):
        raise ImportError_("cdl.fips must be a two-digit state FIPS code")
    with urllib.request.urlopen(f"{CDL_SERVICE}?year={year}&fips={fips}", timeout=300) as resp:
        body = resp.read().decode()
    m = re.search(r"<returnURL>([^<]+)</returnURL>", body)
    if not m:
        raise ImportError_(f"CropScape did not return a file for {year} / {fips}: {body[:300]}")
    return download(m.group(1), f"cdl_{year}_{fips}.tif")


def landfire_raster(zip_path: Path) -> str:
    """The GeoTIFF inside an LFPS zip, as a GDAL path."""
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        tifs = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
    if not tifs:
        raise ImportError_(f"no GeoTIFF in {zip_path.name}")
    return f"/vsizip/{zip_path}/{tifs[0]}"


WSS_ZIP = "https://websoilsurvey.sc.egov.usda.gov/DSD/Download/Cache/SSA/wss_SSA_{area}_[{date}].zip"


def fetch_ssurgo(r: dict) -> tuple[Path, dict[str, str]]:
    """source.ssurgo: the SSURGO map-unit polygons of every survey area matching `areas`, from Web Soil Survey.

    Soil Data Access says which survey areas exist and when each was last saved (sacatalog.saverest); each area
    is one zip (`wss_SSA_ME011_[2026-09-15].zip`) cached per version, so a refresh only fetches areas NRCS
    re-published. The `layer` shapefiles (default soilmu_a, the map-unit polygons) are merged into one GeoPackage.

    ssurgo: {areas: "ME%", layer: soilmu_a}     -> (gpkg, {areasymbol: save date})
    """
    from concurrent.futures import ThreadPoolExecutor
    s = r["source"]["ssurgo"]
    layer = s.get("layer", "soilmu_a")
    if not re.fullmatch(r"soil[a-z]{2}_[a-z]", layer):
        raise ImportError_(f"ssurgo.layer {layer!r} is not a SSURGO spatial layer (soilmu_a, soilmu_l, soilsf_p, ...)")
    versions = freshness.ssurgo_versions(s["areas"])
    if not versions:
        raise ImportError_(f"Soil Data Access lists no survey areas matching {s['areas']}")
    print(f"SSURGO: {len(versions)} survey areas, saved {min(versions.values())} to {max(versions.values())}", flush=True)

    def fetch(area: str) -> Path:
        z = download(WSS_ZIP.format(area=area, date=versions[area]), f"ssurgo_{area}_{versions[area]}.zip")
        for old in DOWNLOADS.glob(f"ssurgo_{area}_*.zip*"):  # earlier versions of this area
            if not old.name.startswith(z.name):
                old.unlink()
        return z

    with ThreadPoolExecutor(4) as pool:
        zips = dict(zip(versions, pool.map(fetch, versions)))
    tag = hashlib.sha256(json.dumps([layer, versions], sort_keys=True).encode()).hexdigest()[:12]
    out = DOWNLOADS.parent / "derived" / f"{r['name']}_{tag}.gpkg"
    if out.exists() and not REDOWNLOAD:
        print(f"using merged {out.relative_to(REPO)}")
        return out, versions
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.gpkg")
    tmp.unlink(missing_ok=True)
    try:
        for i, (area, z) in enumerate(zips.items()):
            shp = f"/vsizip/{z}/{area}/spatial/{layer}_{area.lower()}.shp"
            cmd = ["ogr2ogr", "-f", "GPKG", "-nln", "ssurgo", "-nlt", "PROMOTE_TO_MULTI", "-t_srs", "EPSG:4326",
                   *(["-append"] if i else []), str(tmp), shp]
            if runs.run_cmd(cmd) != 0:
                raise ImportError_(f"ogr2ogr failed on {area} ({shp})")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out)
    for old in out.parent.glob(f"{r['name']}_*.gpkg"):
        if old != out:
            old.unlink()
    return out, versions


def contour_source(r: dict) -> Path:
    """gdal_contour from a COG into a GeoPackage under data/cache/derived/, imported like any vector file."""
    src, c = r["source"], r["source"]["derive"]["contour"]
    base = derived_cog(src)
    out = DOWNLOADS.parent / "derived" / f"{r['name']}.gpkg"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.gpkg")
    tmp.unlink(missing_ok=True)
    cmd = ["gdal_contour", "-q", "-i", str(c["interval"]), "-a", c.get("attribute", "elev"), "-f", "GPKG",
           "-nln", "contours", str(base), str(tmp)]
    print("$ " + shlex.join(cmd), flush=True)
    try:
        rc = runs.run_cmd(cmd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if rc != 0:
        tmp.unlink(missing_ok=True)
        raise ImportError_("gdal_contour failed")
    tmp.replace(out)
    return out


def run_recipe(r: dict) -> dict:
    src = r["source"]
    print(f"\n=== recipe {r['name']} -> {r['target']}")
    if src.get("ssurgo"):
        out, versions = fetch_ssurgo(r)
        stats = do_import(target=r["target"], path=str(out.relative_to(REPO)), layer="ssurgo",
                          srs=r.get("srs", "EPSG:4326"), mode=r.get("mode", "overwrite"), fix=bool(r.get("fix_invalid")),
                          recipe=r["name"], license=r.get("license"),
                          notes=f"SSURGO survey areas saved {min(versions.values())}..{max(versions.values())}"
                                + (f"; {r['notes']}" if r.get("notes") else ""))
        schema, table = r["target"].split(".", 1)
        with psycopg.connect(LOADER) as conn:
            counts = dict(conn.execute(f'SELECT areasymbol, count(*) FROM "{schema}"."{table}" GROUP BY 1').fetchall())
            freshness.record_survey_areas(conn, r["name"], versions, counts,
                                          runs.ACTIVE.run_id if runs.ACTIVE else None)
        return stats
    if src.get("geoparquet"):
        out = fetch_geoparquet(r)
        return do_import(target=r["target"], path=str(out.relative_to(REPO)), layer="features",
                         srs=r.get("srs", "EPSG:4326"), mode=r.get("mode", "overwrite"), fix=bool(r.get("fix_invalid")),
                         recipe=r["name"], license=r.get("license"), notes=r.get("notes"))
    if src.get("overture"):
        out, release = fetch_overture(r)
        return do_import(target=r["target"], path=str(out.relative_to(REPO)), layer="features",
                         srs=r.get("srs", "EPSG:4326"), mode=r.get("mode", "overwrite"), fix=bool(r.get("fix_invalid")),
                         recipe=r["name"], license=r.get("license"),
                         notes=f"Overture Maps release {release}" + (f"; {r['notes']}" if r.get("notes") else ""))
    if src.get("derive", {}).get("contour"):
        out = contour_source(r)
        return do_import(target=r["target"], path=str(out.relative_to(REPO)), layer="contours",
                         srs=r.get("srs", "EPSG:4326"), mode=r.get("mode", "overwrite"), fix=bool(r.get("fix_invalid")),
                         recipe=r["name"], license=r.get("license"), notes=r.get("notes"))
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
        runner = {"raster": run_raster_recipe, "table": run_table_recipe}.get(r.get("kind"), run_recipe)
        stats = runner(r)
        run.rows, run.bytes = stats.get("row_count"), DOWNLOADED_BYTES
        run.outcome = "downloaded" if DOWNLOADED_BYTES else "imported from cached download"
        finalize(r["name"])
    return stats


# Census "annotation" values that stand for suppressed / not applicable estimates.
CENSUS_NULLS = {"-666666666", "-999999999", "-888888888", "-555555555", "-333333333", "-222222222"}
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def census_api_url(c: dict, key: str | None) -> str:
    ins = c.get("in") or []
    q = [("get", ",".join(c["get"])), ("for", c["for"])] + [("in", v) for v in (ins if isinstance(ins, list) else [ins])]
    if key:
        q.append(("key", key))
    return f"https://api.census.gov/data/{c['dataset']}?{urllib.parse.urlencode(q)}"


SDA = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"


def sda_query(query: str) -> tuple[list[str], list[list], bytes]:
    """One query against USDA Soil Data Access (no key). Returns (lowercase column names, rows, raw body)."""
    req = urllib.request.Request(SDA, data=json.dumps({"query": query, "format": "JSON+COLUMNNAME"}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "spatial-geoimport/1"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise ImportError_(f"Soil Data Access returned HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None
    table = json.loads(body).get("Table") or []
    if not table:
        raise ImportError_("Soil Data Access returned no rows")
    return [h.lower() for h in table[0]], table[1:], body


def sda_rows(r: dict) -> tuple[list[str], list[list], dict]:
    """source.sda: {query: "SELECT ...", key: mukey, text_columns: [...]} -> the query's columns as SDA names them."""
    global DOWNLOADED_BYTES
    q = r["source"]["sda"]
    print(f"querying Soil Data Access: {' '.join(q['query'].split())[:160]}…", flush=True)
    names, rows, body = sda_query(q["query"])
    DOWNLOADED_BYTES += len(body)
    return names, rows, {"source": SDA, "label": "USDA Soil Data Access", "body": body, "key": q.get("key"),
                         "text": set(q.get("text_columns") or []), "note": ""}


def run_table_recipe(r: dict) -> dict:
    """kind: table -> a non-spatial src_* table (source.census_api or source.sda), replaced in one transaction.

    The table is emptied and refilled rather than dropped, so pub views built on it survive a refresh.
    Columns whose values are all numbers become numeric (except the key and `text_columns`), the rest text.
    """
    target = r["target"]
    schema, table = target.split(".", 1)
    print(f"\n=== recipe {r['name']} -> {target}")
    names, records, prov = (census_rows if r["source"].get("census_api") else sda_rows)(r)
    if not all(IDENT.match(x) for x in [schema, table, *names]):
        raise ImportError_(f"{r['name']}: target and column names must be lowercase identifiers")
    key = prov["key"]
    if key and key not in names:
        raise ImportError_(f"{r['name']}: key column {key!r} is not in the result ({names})")
    defs = []
    for i, col in enumerate(names):
        numeric = col != key and col not in prov["text"] and all(
            row[i] is None or re.fullmatch(r"-?\d+(\.\d+)?", str(row[i])) for row in records)
        defs.append(f"{col} {'numeric' if numeric else 'text'}" + (" PRIMARY KEY" if col == key else ""))
    q = f'"{schema}"."{table}"'
    with psycopg.connect(LOADER) as conn:
        existing = [x[0] for x in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
            "ORDER BY ordinal_position", (schema, table)).fetchall()]
        if existing and existing != names:
            raise ImportError_(f"{target} exists with columns {existing}, the recipe now gives {names}; "
                               "drop it (and dependent views) deliberately before changing columns")
        if not existing:
            conn.execute(f"CREATE TABLE {q} ({', '.join(defs)})")
        conn.execute(f"TRUNCATE {q}")
        with conn.cursor().copy(f"COPY {q} ({', '.join(names)}) FROM STDIN") as cp:
            for rec in records:
                cp.write_row(rec)
        conn.execute(psycopg.sql.SQL("COMMENT ON TABLE {} IS {}").format(
            psycopg.sql.Identifier(schema, table),
            psycopg.sql.Literal(f"{r.get('title', r['name'])} ({prov['label']}); recipe {r['name']}")))
        conn.execute(f"ANALYZE {q}")
        digest = hashlib.sha256(prov["body"]).hexdigest()
        stats = {"geometry_type": None, "srid": None, "row_count": len(records), "invalid_geom_count": None}
        record(conn, schema, table, source=prov["source"], layer=None, digest=digest, source_srs=None,
               target_srs=None, stats=stats, recipe=r["name"], license=r.get("license"), notes=r.get("notes"))
    print(f"OK {target}: {len(records)} rows, {len(names)} columns" + (f", {prov['note']}" if prov["note"] else ""))
    return stats


def census_rows(r: dict) -> tuple[list[str], list[list], dict]:
    """source.census_api -> (column names, rows, provenance). Annotation values (suppressed estimates) become NULL."""
    global DOWNLOADED_BYTES
    c = r["source"]["census_api"]
    columns = c["get"]  # {api variable: column name}
    url = census_api_url(c, os.environ.get("CENSUS_API_KEY"))
    print(f"downloading {redact(url)}", flush=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise ImportError_(f"Census API returned HTTP {e.code}: {redact(e.read().decode(errors='replace'))[:300]}") from None
    DOWNLOADED_BYTES += len(body)
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        raise ImportError_(f"Census API did not return JSON (bad key?): {redact(body[:200].decode(errors='replace'))}") from None
    header, data = rows[0], rows[1:]
    idx = {h: i for i, h in enumerate(header)}
    geo_parts = c.get("geoid") or []
    suppressed = 0
    records = []
    for row in data:
        out = ["".join(row[idx[g]] for g in geo_parts)] if geo_parts else []
        for v in columns:
            val = row[idx[v]]
            if val in CENSUS_NULLS:
                val, suppressed = None, suppressed + 1
            out.append(val)
        records.append(out)
    names = (["geoid"] if geo_parts else []) + list(columns.values())
    return names, records, {"source": census_api_url(c, None), "label": c["dataset"], "body": body,
                            "key": "geoid" if geo_parts else None, "text": set(),
                            "note": f"{suppressed} suppressed values -> NULL"}


COG_NAME = re.compile(r"^[a-z0-9_/-]+$")


def tile_mosaic(r: dict) -> Path:
    """source.tiles: a tile grid (e.g. USGS 3DEP 1x1 degree COGs) -> a VRT of the tiles that exist, read over HTTP.

    tiles: {template: ".../{tile}/USGS_1_{tile}.tif", north: [43, 48], west: [67, 72]}  (tile = n<lat>w<lon>)
    """
    from concurrent.futures import ThreadPoolExecutor
    t = r["source"]["tiles"]
    names = [f"n{n:02d}w{w:03d}" for n in range(t["north"][0], t["north"][1] + 1)
             for w in range(t["west"][0], t["west"][1] + 1)]
    urls = [t["template"].format(tile=n) for n in names]

    def exists(u: str) -> bool:
        try:
            with urllib.request.urlopen(urllib.request.Request(u, method="HEAD"), timeout=30) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001  missing tiles (open ocean) answer 403/404
            return False

    with ThreadPoolExecutor(8) as ex:
        found = [u for u, ok in zip(urls, ex.map(exists, urls)) if ok]
    if not found:
        raise ImportError_("source.tiles: none of the tiles exist; check the template")
    print(f"tiles: {len(found)} of {len(urls)} exist", flush=True)
    vrt = DOWNLOADS / f"{r['name']}.vrt"
    vrt.parent.mkdir(parents=True, exist_ok=True)
    listing = vrt.with_suffix(".txt")
    listing.write_text("\n".join(f"/vsicurl/{u}" for u in found) + "\n")
    if runs.run_cmd(["gdalbuildvrt", "--config", "GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR", "-q", "-overwrite",
                     "-input_file_list", str(listing), str(vrt)]) != 0:
        raise ImportError_("gdalbuildvrt failed")
    return vrt


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
    dest = COG_DIR / f"{name}.tif"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.stem}.tmp.tif")
    tmp.unlink(missing_ok=True)
    cog_co = ["-of", "COG", "-co", "COMPRESS=DEFLATE", "-co", "OVERVIEWS=AUTO", "-co", "BLOCKSIZE=512",
              "-co", "BIGTIFF=IF_SAFER", "-co", "NUM_THREADS=ALL_CPUS"]
    if r.get("resampling") == "nearest" or src.get("rasterize"):  # classes: overviews must not average codes
        cog_co += ["-co", "RESAMPLING=NEAREST"]
    for o in r.get("cog_options") or []:
        cog_co += ["-co", str(o)]
    # Reading remote COG tiles: no directory listings, a block cache, and retries.
    net = ["--config", "GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR", "--config", "VSI_CACHE", "TRUE",
           "--config", "GDAL_CACHEMAX", "1024", "--config", "GDAL_HTTP_MAX_RETRY", "5",
           "--config", "GDAL_HTTP_RETRY_DELAY", "3", "--config", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.vrt"]
    derive = src.get("derive")
    stage = None
    if derive and derive.get("gdaldem"):
        # A product of another COG (hillshade, slope, ...): gdaldem to a tiled GeoTIFF, then COG.
        local = derived_cog(src)
        mode, *opts = [str(x) for x in derive["gdaldem"]]
        stage = dest.with_name(f".{dest.stem}.gdaldem.tif")
        steps = [["gdaldem", mode, str(local), str(stage), *opts, "-of", "GTiff", "-co", "TILED=YES",
                  "-co", "COMPRESS=DEFLATE", "-co", "BIGTIFF=IF_SAFER"],
                 ["gdal_translate", *cog_co, str(stage), str(tmp)]]
    elif src.get("rasterize"):
        # PostGIS polygons burned into a grid (e.g. soil classes as small integer codes), then COG.
        rz, res = src["rasterize"], float(r.get("resolution", 30))
        srid = int(r.get("srs", "EPSG:26919").split(":")[1])
        sql = f"SELECT {rz['attribute']} AS v, ST_Transform(geom, {srid}) AS geom FROM ({rz['sql']}) s"
        if not IDENT.match(rz["attribute"]):
            raise ImportError_("rasterize.attribute must be a column name")
        with psycopg.connect(LOADER) as conn:
            xmin, ymin, xmax, ymax = conn.execute(
                f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM (SELECT ST_Extent(geom) e FROM ({sql}) q) x"
            ).fetchone()
        snap = lambda v, up: (math.ceil if up else math.floor)(v / res) * res  # noqa: E731
        local = Path("/dev/null")  # no downloaded source file
        stage = dest.with_name(f".{dest.stem}.rasterize.tif")
        steps = [["gdal_rasterize", "-q", "-sql", sql, "-a", "v", "-a_srs", f"EPSG:{srid}",
                  "-te", *[str(v) for v in (snap(xmin, False), snap(ymin, False), snap(xmax, True), snap(ymax, True))],
                  "-tr", str(res), str(res), "-ot", rz.get("type", "Byte"), "-a_nodata", "0", "-init", "0",
                  "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "PG:service=loader", str(stage)],
                 ["gdal_translate", *cog_co, str(stage), str(tmp)]]
    else:
        if src.get("tiles"):
            local = tile_mosaic(r)
            gsrc = str(local)
        elif src.get("landfire"):
            local = fetch_landfire(r)
            gsrc = landfire_raster(local)
        elif src.get("cdl"):
            local = fetch_cdl(r)
            gsrc = str(local)
        elif src.get("url") and src.get("stream"):
            # A remote COG (optionally inside a zip stored without compression) read by HTTP range requests:
            # only the blocks inside the target extent are fetched, not the whole national file.
            local = Path("/dev/null")
            gsrc = f"/vsizip//vsicurl/{src['url']}/{src['inner']}" if src.get("inner") else f"/vsicurl/{src['url']}"
            net += ["--config", "CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".zip,.tif"]
        else:
            local = download(src["url"], src.get("filename")) if src.get("url") else resolve(src["path"])
            gsrc = gdal_path(local) + (f"/{src['inner']}" if src.get("inner") else "")
        res = str(r.get("resolution", 100))
        cmd = ["gdalwarp", "-overwrite", *net, "-t_srs", r.get("srs", "EPSG:26919"), "-tr", res, res,
               "-r", r.get("resampling", "bilinear"), "-dstnodata", str(r.get("nodata", -9999)),
               "-multi", "-wo", "NUM_THREADS=ALL_CPUS", "-wm", "1024"]
        if r.get("cutline_sql"):
            cmd += ["-cutline", "PG:service=loader", "-csql", r["cutline_sql"], "-crop_to_cutline"]
        elif r.get("spat"):
            cmd += ["-te_srs", "EPSG:4326", "-te", *[str(v) for v in r["spat"]]]
        steps = [cmd + [*cog_co, gsrc, str(tmp)]]
    try:
        for cmd in steps:
            print("$ " + redact(shlex.join(cmd)), flush=True)
            if runs.run_cmd(cmd) != 0:
                raise ImportError_(f"{cmd[0]} failed")
    except BaseException:
        tmp.unlink(missing_ok=True)
        if stage:
            stage.unlink(missing_ok=True)
        raise
    if stage:
        stage.unlink(missing_ok=True)

    # Validate before swapping in: COG layout, CRS, and at least some valid pixels.
    gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")  # no .aux.xml side files
    info = gdal.Info(str(tmp), format="json")
    ds = gdal.Open(str(tmp))
    band = ds.GetRasterBand(1)
    try:
        mn, mx, mean, _std = band.ComputeStatistics(ds.RasterXSize * ds.RasterYSize > 50_000_000)  # approximate when big
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
        if src.get("url") and not src.get("stream"):  # streamed sources leave no local file
            freshness.record_loaded_part(conn, r["name"], local, run_id, src_digest, None)
        conn.commit()
    print(f"OK data/cog/{name}.tif: {raster['width']}x{raster['height']} {raster['dtype']}, {raster['crs']}, "
          f"{raster['resolution'][0]:g} m, values {mn:.2f} .. {mx:.2f}")
    return {"row_count": None, "raster": raster}


def cmd_recipe(args) -> None:
    global REDOWNLOAD
    sync_quietly()
    r = load_recipe(args.name)
    if r.get("enabled") is False and not args.force:
        raise ImportError_(f"recipe {args.name} is disabled (todo: {r.get('todo', '-')}). "
                           "Set enabled: true, or run with force=1.")
    REDOWNLOAD = bool(args.redownload)
    run_recorded(r, {"force": bool(args.force), "redownload": REDOWNLOAD})


def _recorded(action: str, name: str | None):
    """Record health/freshness/plan/set-enabled as runs when the dataset worker runs them (JOB_ID set)."""
    import contextlib
    if os.environ.get("JOB_ID") and name:
        return runs.RunRecorder(action, recipe=name, concurrency="db")
    return contextlib.nullcontext()


def cmd_plan(args) -> None:
    """Dry run: what an import of this recipe would download and replace, without changing anything."""
    sync_quietly()
    r = load_recipe(args.name)
    src = r["source"]
    with _recorded("dry_run", r["name"]) as run:
        report: dict = {"recipe": r["name"], "kind": r.get("kind", "vector"), "enabled": r.get("enabled", True) is not False,
                        "target": r["target"]}
        if src.get("url"):
            dest = DOWNLOADS / (src.get("filename") or src["url"].rstrip("/").rsplit("/", 1)[-1])
            cached = dest.stat().st_size if dest.exists() else None
            try:
                up = freshness.head(src["url"])
            except Exception as e:  # noqa: BLE001  report it; a dry run never fails on an unreachable source
                up = {"error": f"{type(e).__name__}: {e}"[:200]}
            side = freshness.headers_sidecar(dest)
            held = json.loads(side.read_text()) if side.exists() else {}
            same = bool(cached) and freshness.marker(up) is not None and freshness.marker(up) == freshness.marker(held)
            report.update({"source": redact(src["url"]), "upstream_bytes": up.get("bytes"),
                           "upstream_version": freshness.marker(up), "upstream_error": up.get("error"),
                           "cached_bytes": cached, "cached_version": freshness.marker(held),
                           "would": "import from the cached download (upstream unchanged)" if same else
                                    ("download, then import" if not cached else "download the newer upstream file, then import")})
        elif src.get("arcgis"):
            a = src["arcgis"]
            q = urllib.parse.urlencode({"where": a.get("where", "1=1"), "returnCountOnly": "true", "f": "json"})
            try:
                with urllib.request.urlopen(f"{a['url']}/query?{q}", timeout=60) as resp:
                    count = json.load(resp).get("count")
            except Exception as e:  # noqa: BLE001
                count = None
                report["upstream_error"] = f"{type(e).__name__}: {e}"[:200]
            report.update({"source": redact(a["url"]), "upstream_features": count,
                           "would": "fetch every feature from the ArcGIS service, then import"})
        elif src.get("census_api"):
            report.update({"source": src["census_api"]["dataset"], "would": "query the Census Data API, then replace the table"})
        else:
            report.update({"source": src.get("path"), "would": "import the local file"})
        with psycopg.connect(LOADER) as conn:
            cur = conn.execute("SELECT row_count, bytes FROM app.dataset_outputs WHERE recipe_name = %s "
                               "AND kind IN ('postgis_table', 'cog') ORDER BY kind DESC LIMIT 1", (r["name"],)).fetchone()
        report.update({"current_rows": cur[0] if cur else None, "current_bytes": cur[1] if cur else None})
        print("PLAN " + json.dumps(report))
        if run:
            run.report, run.outcome = report, report["would"]


def cmd_set_enabled(args) -> None:
    """Enable or disable a recipe by editing `enabled:` in its YAML (the registry follows on sync)."""
    path = RECIPES / f"{args.name}.yaml"
    if not path.exists():
        raise ImportError_(f"no recipe {args.name}")
    value = {"true": True, "false": False}[args.value]
    with _recorded("set_enabled", args.name) as run:
        text = path.read_text()
        line = f"enabled: {'true' if value else 'false'}"
        text = re.sub(r"(?m)^enabled:.*$", line, text) if re.search(r"(?m)^enabled:", text) else text.rstrip("\n") + f"\n{line}\n"
        path.write_text(text)
        load_recipe(args.name)  # still valid
        sync_quietly()
        print(f"{args.name}: {line}")
        if run:
            run.outcome = line


def cmd_all(args) -> None:
    sync_quietly()
    names = [p.stem for p in sorted(RECIPES.glob("*.yaml"))]
    deps = {}
    for n in names:
        try:
            deps[n] = [d for d in (yaml.safe_load((RECIPES / f"{n}.yaml").read_text()).get("depends_on") or []) if d in names]
        except yaml.YAMLError:
            deps[n] = []
    ordered: list[str] = []

    def visit(n: str, trail: tuple = ()) -> None:  # dependencies first (depends_on), otherwise alphabetical
        if n in ordered or n in trail:
            return
        for d in deps.get(n, []):
            visit(d, trail + (n,))
        ordered.append(n)

    for n in names:
        visit(n)
    names = ordered
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
    with _recorded("healthcheck", args.name) as run:
        with psycopg.connect(LOADER) as conn:
            outputs_mod.refresh_outputs(conn, args.name, PROJECTS)
            results = health.check_outputs(conn, args.name)
        for kind, locator, state, detail in results:
            print(f"{state.upper():<8}{kind:<17}{locator:<45}{detail}")
        if run:
            run.report = {"outputs": [{"kind": k, "locator": l, "health": s, "detail": d} for k, l, s, d in results]}
            run.outcome = ", ".join(f"{sum(r[2] == s for r in results)} {s}" for s in ("ok", "warn", "fail")
                                    if any(r[2] == s for r in results))
        if any(r[2] == "fail" for r in results):
            raise ImportError_("some outputs failed their health check")


def cmd_freshness(args) -> None:
    sync_quietly()
    with _recorded("freshness", args.name) as run:
        with psycopg.connect(LOADER) as conn:
            results = freshness.check(conn, args.name, DOWNLOADS)
        for name, verdict, detail in results:
            print(f"{verdict.upper():<9}{name:<24}{detail}")
        if run and results:
            run.outcome = f"{results[0][1]}: {results[0][2]}"[:200]
            run.report = {"verdict": results[0][1], "detail": results[0][2]}


# --------------------------------------------------------------------------- main

def _terminate(signum, frame):
    # The dataset worker cancels a job with SIGTERM: unwind like Ctrl-C, so partial downloads are removed and the
    # run is recorded as cancelled (RunRecorder treats KeyboardInterrupt as a cancellation).
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _terminate)
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
    p.add_argument("--redownload", action="store_true", help="ignore the cached download and fetch it again")
    p.set_defaults(func=cmd_recipe)

    p = sub.add_parser("plan", help="dry run: what an import would download and replace")
    p.add_argument("name")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("set-enabled", help="enable or disable a recipe (edits its YAML)")
    p.add_argument("name")
    p.add_argument("value", choices=["true", "false"])
    p.set_defaults(func=cmd_set_enabled)

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
