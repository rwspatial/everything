#!/usr/bin/env python3
"""Phase 1 checks that run inside the geotools container.

Called by scripts/verify.sh after it has fetched tiles/items from the proxy into
data/cache/verify/ and written data/cache/verify/expect.json. Exit code 1 if any check fails.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import psycopg  # noqa: E402
from osgeo import gdal, osr  # noqa: E402

import geoimport  # noqa: E402

gdal.UseExceptions()
VERIFY = Path("/work/data/cache/verify")
results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def rscript(expr: str) -> subprocess.CompletedProcess:
    return run(["Rscript", "--vanilla", "-e", expr])


# --------------------------------------------------------------------------- toolbox

def versions() -> None:
    import pyogrio
    import pyproj
    import rasterio

    cli = re.search(r"GDAL (\S+),", run(["gdalinfo", "--version"]).stdout)
    gdal_versions = {
        "cli": cli.group(1) if cli else "?",
        "py-osgeo": gdal.__version__,
        "pyogrio": pyogrio.__gdal_version_string__,
        "rasterio": rasterio.__gdal_version__,
        "R-sf": rscript('cat(sf::sf_extSoftVersion()[["GDAL"]])').stdout.strip() or "?",
    }
    check("one GDAL version across CLI / Python / R", len(set(gdal_versions.values())) == 1,
          ", ".join(f"{k}={v}" for k, v in gdal_versions.items()))

    proj_versions = {
        "py-osgeo": f"{osr.GetPROJVersionMajor()}.{osr.GetPROJVersionMinor()}.{osr.GetPROJVersionMicro()}",
        "pyproj": pyproj.proj_version_str,
        "R-sf": rscript('cat(sf::sf_extSoftVersion()[["PROJ"]])').stdout.strip() or "?",
    }
    check("one PROJ version across Python / R", len(set(proj_versions.values())) == 1,
          ", ".join(f"{k}={v}" for k, v in proj_versions.items()))


def readers() -> None:
    r = rscript(
        'con <- DBI::dbConnect(RPostgres::Postgres()); '
        'x <- sf::st_read(con, query = "SELECT * FROM pub.world_overview__countries", quiet = TRUE); '
        'cat(nrow(x), sf::st_crs(x)$epsg)'
    )
    parts = r.stdout.split()
    ok = r.returncode == 0 and len(parts) == 2 and int(parts[0]) > 0 and parts[1] == "4326"
    check("R (sf + RPostgres) reads a PostGIS view", ok,
          f"rows={parts[0]} epsg={parts[1]}" if len(parts) == 2 else r.stderr.strip()[-300:])

    try:
        import geopandas as gpd
        import sqlalchemy

        eng = sqlalchemy.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect("service=analyst"))
        gdf = gpd.read_postgis("SELECT * FROM pub.world_overview__countries", eng, geom_col="geom")
        check("Python (geopandas + psycopg) reads a PostGIS view", len(gdf) > 0 and gdf.crs.to_epsg() == 4326,
              f"rows={len(gdf)} crs={gdf.crs}")
    except Exception as e:  # noqa: BLE001 - report any failure as a failed check
        check("Python (geopandas + psycopg) reads a PostGIS view", False, repr(e)[:300])


# --------------------------------------------------------------------------- privileges

def attempt(service: str, sql: str) -> str:
    try:
        with psycopg.connect(f"service={service}") as conn:
            conn.execute(sql)
            conn.rollback()
        return "allowed"
    except psycopg.errors.InsufficientPrivilege:
        return "denied"
    except psycopg.Error as e:
        return f"error: {str(e).strip()[:200]}"


def privileges() -> None:
    cases = [
        ("tipg", "SELECT 1 FROM pub.world_overview__countries LIMIT 1", "allowed"),
        ("tipg", "SELECT 1 FROM src_ne.countries LIMIT 1", "denied"),
        ("tipg", "SELECT 1 FROM app.datasets LIMIT 1", "denied"),
        ("loader", "CREATE TABLE pub._verify_x (id int)", "denied"),
        ("loader", "CREATE TABLE app._verify_x (id int)", "denied"),
        ("analyst", "SELECT 1 FROM src_ne.countries LIMIT 1", "allowed"),
        ("analyst", "INSERT INTO app.dataset_outputs (kind, locator) VALUES ('pub_view', 'pub.x')", "denied"),
        ("analyst", "INSERT INTO app.runs (action, status, triggered_by) VALUES ('import', 'failed', 'x')", "denied"),
        ("tipg", "SELECT 1 FROM app.runs LIMIT 1", "denied"),
    ]
    for service, sql, expected in cases:
        got = attempt(service, sql)
        check(f"{service:<7} {expected:<7} {sql[:70]}", got == expected, "" if got == expected else f"got {got}")


# --------------------------------------------------------------------------- tiles / items

def mvt_counts(path: Path) -> dict[str, int]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    ds = gdal.OpenEx(f"MVT:{path}", gdal.OF_VECTOR)
    return {ds.GetLayer(i).GetName(): ds.GetLayer(i).GetFeatureCount() for i in range(ds.GetLayerCount())}


def tiles(expect: dict) -> None:
    for t in expect["tiles"]:
        counts = mvt_counts(VERIFY / t["file"])
        n = counts.get(t["layer"], 0)
        check(f"MVT decodes: {t['file']}", n >= t["min"], f"layers={counts}")
    for a, b in expect.get("fewer_than", []):
        na, nb = sum(mvt_counts(VERIFY / a).values()), sum(mvt_counts(VERIFY / b).values())
        check("function collection honours its query parameter", 0 < na < nb,
              f"{a}: {na} features < {b}: {nb} features")


def items(expect: dict) -> None:
    spec = expect["items"]
    doc = json.loads((VERIFY / spec["file"]).read_text())
    matched = doc.get("numberMatched")
    minx, miny, maxx, maxy = spec["bbox"]
    with psycopg.connect("service=analyst") as conn:
        n = conn.execute(
            f"SELECT count(*) FROM {spec['view']} WHERE ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))",
            (minx, miny, maxx, maxy),
        ).fetchone()[0]
    check("GeoJSON items bbox count matches PostGIS", matched == n and n > 0, f"tiPG numberMatched={matched}, SQL={n}")


# --------------------------------------------------------------------------- import formats

def formats() -> None:
    out = VERIFY / "formats"
    out.mkdir(parents=True, exist_ok=True)
    gpkg, csv = out / "places.gpkg", out / "places.csv"
    base_sql = "SELECT id AS src_id, name, pop_max, geom FROM pub.world_overview__places"
    run(["ogr2ogr", "-f", "GPKG", "-overwrite", str(gpkg), "PG:service=analyst", "-sql", base_sql,
         "-nln", "places", "-nlt", "POINT", "-a_srs", "EPSG:4326"])
    run(["ogr2ogr", "-f", "CSV", "-overwrite", str(csv), "PG:service=analyst", "-sql",
         "SELECT name, pop_max, ST_X(geom) AS lon, ST_Y(geom) AS lat FROM pub.world_overview__places"])
    with psycopg.connect("service=analyst") as conn:
        expected = conn.execute("SELECT count(*) FROM pub.world_overview__places").fetchone()[0]

    for path, target in [(gpkg, "src_ne._verify_gpkg"), (csv, "src_ne._verify_csv")]:
        try:
            stats = geoimport.do_import(target=target, path=str(path), notes="make verify (temporary)")
            check(f"import {path.suffix} -> {target}", stats["row_count"] == expected and stats["srid"] == 4326,
                  f"rows={stats['row_count']}/{expected} srid={stats['srid']} type={stats['geometry_type']}")
        except Exception as e:  # noqa: BLE001
            check(f"import {path.suffix} -> {target}", False, str(e)[:300])

    with psycopg.connect("service=loader") as conn:
        n = conn.execute("SELECT count(*) FROM app.datasets WHERE table_name IN ('_verify_gpkg', '_verify_csv')").fetchone()[0]
        check("imports recorded in app.datasets", n == 2, f"{n}/2 rows")
        conn.execute("DROP TABLE IF EXISTS src_ne._verify_gpkg, src_ne._verify_csv")
        conn.execute("DELETE FROM app.datasets WHERE table_name IN ('_verify_gpkg', '_verify_csv')")

    with psycopg.connect("service=loader") as conn:
        rows = conn.execute(
            "SELECT recipe, row_count, source_srs FROM app.datasets WHERE recipe LIKE 'ne\\_%' ORDER BY recipe"
        ).fetchall()
    ok = len(rows) >= 4 and all(r[1] and r[1] > 0 for r in rows)
    check("Natural Earth recipes (zipped shapefiles) recorded", ok,
          ", ".join(f"{r[0]}={r[1]} ({r[2]})" for r in rows) or "none: run make import-all")


def redaction() -> None:
    """A canary secret printed, logged and raised inside a recorded run must never reach app.runs."""
    import os
    import secrets

    from etl import runs as runs_mod

    canary = "canary" + secrets.token_hex(12)
    os.environ["SPATIAL_VERIFY_API_KEY"] = canary
    run_id = None
    try:
        with runs_mod.RunRecorder("dry_run", params={"verify": "redaction"}) as rec:
            run_id = rec.run_id
            print(f"GET https://upstream.invalid/data?key={canary}&year=2024")
            print(f"Authorization: Bearer {canary}")
            raise RuntimeError(f"upstream rejected key {canary}")
    except RuntimeError:
        pass
    finally:
        os.environ.pop("SPATIAL_VERIFY_API_KEY", None)
    with psycopg.connect("service=loader") as conn:
        text, status, job_id = conn.execute(
            "SELECT coalesce(log_tail, '') || coalesce(error, ''), status, job_id FROM app.runs WHERE id = %s",
            (run_id,)).fetchone()
        conn.execute("DELETE FROM app.runs WHERE id = %s", (run_id,))
        conn.execute("DELETE FROM app.jobs WHERE id = %s", (job_id,))
    check("secrets are redacted from run logs and errors", canary not in text and "•••" in text and status == "failed",
          f"run {run_id}: status {status}, canary {'LEAKED' if canary in text else 'absent'}")


def make_test_cog() -> None:
    """data/cog/_verify/gradient.tif: 256 km square over central Maine (UTM 19N), values 0..1600."""
    import numpy as np
    out = Path("/work/data/cog/_verify")
    out.mkdir(parents=True, exist_ok=True)
    x, y = np.meshgrid(np.linspace(0, 1, 256), np.linspace(1, 0, 256))
    mem = gdal.GetDriverByName("MEM").Create("", 256, 256, 1, gdal.GDT_Float32)
    mem.SetGeoTransform((400000, 1000, 0, 5100000, 0, -1000))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(26919)
    mem.SetProjection(srs.ExportToWkt())
    band = mem.GetRasterBand(1)
    band.WriteArray((1600 * (0.5 * x + 0.5 * y)).astype("float32"))
    band.SetNoDataValue(-9999)
    gdal.Translate(str(out / "gradient.tif"), mem, format="COG", creationOptions=["COMPRESS=DEFLATE", "OVERVIEWS=AUTO"])


def main() -> int:
    if sys.argv[1:] == ["make-test-cog"]:
        make_test_cog()
        return 0
    expect = json.loads((VERIFY / "expect.json").read_text())
    print("-- toolbox")
    versions()
    readers()
    print("-- database privileges")
    privileges()
    print("-- tiles and features (fetched through the proxy)")
    tiles(expect)
    items(expect)
    print("-- import formats")
    formats()
    print("-- run history")
    redaction()
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
