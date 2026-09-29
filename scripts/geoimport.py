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

<file> is looked up in data/incoming/ (mounted at /data), then relative to the repo.
Zip files are read in place through /vsizip/.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

import psycopg
import yaml
from osgeo import gdal, ogr

gdal.UseExceptions()

REPO = Path("/work")
INCOMING = Path("/data")
DOWNLOADS = REPO / "data" / "cache" / "downloads"
RECIPES = REPO / "data" / "recipes"
COG_DIR = REPO / "data" / "cog"

LOADER = "service=loader"
TARGET_RE = re.compile(r"^(src_[a-z][a-z0-9_]*)\.([a-z_][a-z0-9_]*)$")
CSV_XY = ["X_POSSIBLE_NAMES=lon*,long*,x", "Y_POSSIBLE_NAMES=lat*,y", "AUTODETECT_TYPE=YES"]
RECIPE_KEYS = {"name", "description", "source", "target", "srs", "src_srs", "mode",
               "fix_invalid", "clip_web_mercator", "open_options", "license", "notes", "enabled", "todo"}


class ImportError_(Exception):
    """A user-facing failure: printed without a traceback."""


# --------------------------------------------------------------------------- sources

def download(url: str) -> Path:
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS / url.rstrip("/").rsplit("/", 1)[-1]
    if dest.exists() and dest.stat().st_size > 0:
        print(f"using cached download {dest.relative_to(REPO)}")
        return dest
    print(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "spatial-geoimport/1"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    tmp.rename(dest)
    return dest


def resolve(path: str) -> Path:
    p = Path(path)
    for candidate in ([p] if p.is_absolute() else [INCOMING / p, REPO / p]):
        if candidate.exists():
            return candidate
    raise ImportError_(f"file not found: {path} (looked in data/incoming/ and the repo root)")


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
    conn.execute(
        """
        INSERT INTO app.datasets (table_schema, table_name, source, source_layer, source_sha256,
            source_srs, target_srs, geometry_type, srid, row_count, invalid_geom_count,
            recipe, license, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (table_schema, table_name) DO UPDATE SET
            source = EXCLUDED.source, source_layer = EXCLUDED.source_layer,
            source_sha256 = EXCLUDED.source_sha256, source_srs = EXCLUDED.source_srs,
            target_srs = EXCLUDED.target_srs, geometry_type = EXCLUDED.geometry_type,
            srid = EXCLUDED.srid, row_count = EXCLUDED.row_count,
            invalid_geom_count = EXCLUDED.invalid_geom_count, recipe = EXCLUDED.recipe,
            license = COALESCE(EXCLUDED.license, app.datasets.license),
            notes = COALESCE(EXCLUDED.notes, app.datasets.notes),
            imported_at = now(), imported_by = current_user
        """,
        (schema, table, source, layer, digest, source_srs, target_srs, stats["geometry_type"],
         stats["srid"], stats["row_count"], stats["invalid_geom_count"], recipe, license, notes),
    )
    conn.commit()


def do_import(*, target: str, path: str | None = None, url: str | None = None, layer: str | None = None,
              srs: str = "EPSG:4326", src_srs: str | None = None, mode: str = "overwrite", fix: bool = False, clip: bool = False,
              oo: list[str] | None = None, recipe: str | None = None, license: str | None = None,
              notes: str | None = None) -> dict:
    m = TARGET_RE.match(target)
    if not m:
        raise ImportError_(f"target must be src_<domain>.<table> in lowercase, got '{target}'")
    schema, table = m.groups()
    if mode not in ("overwrite", "append"):
        raise ImportError_(f"mode must be overwrite or append, got '{mode}'")

    local = download(url) if url else resolve(path)
    oo = open_options_for(local, oo or [])
    if is_csv(local) and not src_srs:
        src_srs = "EPSG:4326"  # lon/lat CSVs carry no CRS; override with src_srs=
    gpath = gdal_path(local)
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
    print("$ " + shlex.join(cmd), flush=True)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        if deps:
            with psycopg.connect(LOADER) as conn:
                conn.execute(f'DROP TABLE IF EXISTS "{schema}"."{load_table}"')
        raise ImportError_(f"ogr2ogr failed with exit code {result.returncode}"
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
        record(conn, schema, table, source=url or str(path), layer=layer_name, digest=sha256(local),
               source_srs=source_srs, target_srs=srs, stats=stats, recipe=recipe,
               license=license, notes=notes)

    print(f"OK {schema}.{table}: {stats['row_count']} rows, {stats['geometry_type']}, SRID {stats['srid']}"
          + (f", {stats['invalid_geom_count']} INVALID geometries (re-run with fix=1)" if stats["invalid_geom_count"] else ""))
    return stats


def cmd_import(args) -> None:
    do_import(target=args.target, path=args.file, layer=args.layer, srs=args.srs, src_srs=args.src_srs,
              mode=args.mode, fix=args.fix, clip=args.clip, oo=args.oo, license=args.license, notes=args.notes)
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
    if bool(src.get("url")) == bool(src.get("path")):
        raise ImportError_(f"{path.name}: source needs exactly one of url or path")
    if "target" not in r:
        raise ImportError_(f"{path.name}: missing target")
    return r


def run_recipe(r: dict) -> dict:
    src = r["source"]
    print(f"\n=== recipe {r['name']} -> {r['target']}")
    return do_import(target=r["target"], path=src.get("path"), url=src.get("url"), layer=src.get("layer"),
                     srs=r.get("srs", "EPSG:4326"), src_srs=r.get("src_srs"), mode=r.get("mode", "overwrite"),
                     fix=bool(r.get("fix_invalid")), clip=bool(r.get("clip_web_mercator")), oo=r.get("open_options") or [], recipe=r["name"],
                     license=r.get("license"), notes=r.get("notes"))


def cmd_recipe(args) -> None:
    r = load_recipe(args.name)
    if r.get("enabled") is False and not args.force:
        raise ImportError_(f"recipe {args.name} is disabled (todo: {r.get('todo', '-')}). "
                           "Set enabled: true, or run with force=1.")
    run_recipe(r)


def cmd_all(_args) -> None:
    names = [p.stem for p in sorted(RECIPES.glob("*.yaml"))]
    failed, skipped = [], []
    for name in names:
        try:
            r = load_recipe(name)
            if r.get("enabled") is False:
                skipped.append(f"{name} (todo: {r.get('todo', '-')})")
                continue
            run_recipe(r)
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
    print("$ " + shlex.join(cmd), flush=True)
    if subprocess.run(cmd).returncode != 0:
        raise ImportError_("gdal_translate failed")
    print(f"OK wrote {dest.relative_to(REPO)}")


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

    sub.add_parser("all").set_defaults(func=cmd_all)

    p = sub.add_parser("list")
    p.add_argument("--no-recipe", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("cog")
    p.add_argument("file")
    p.set_defaults(func=cmd_cog)

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
