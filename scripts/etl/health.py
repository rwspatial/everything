"""Live health checks per output (plan §4.6). Results land in app.dataset_outputs.health*.

postgis_table    table exists and has rows
pub_view         tiPG's own role can read it (proves the grant, not just existence)
tipg_collection  tiPG answers for the collection and returns data (items for views, a tile for functions)
"""
from __future__ import annotations

import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import psycopg
from osgeo import gdal

TIPG = "http://tipg:8000"
gdal.UseExceptions()


def _get(url: str, timeout: int = 30) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, str(e).encode()


def _is_function(conn, obj: str) -> bool:
    schema, name = obj.split(".", 1)
    return bool(conn.execute(
        "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %s AND p.proname = %s",
        (schema, name)).fetchone())


def check_postgis_table(conn, locator: str) -> tuple[str, str]:
    if not conn.execute("SELECT to_regclass(%s)", (locator,)).fetchone()[0]:
        return "fail", "table does not exist"
    schema, table = locator.split(".", 1)
    has_row = conn.execute(f'SELECT EXISTS (SELECT 1 FROM "{schema}"."{table}")').fetchone()[0]
    return ("ok", "has rows") if has_row else ("warn", "table is empty")


def check_pub_object(conn, locator: str) -> tuple[str, str]:
    function = _is_function(conn, locator)
    try:
        with psycopg.connect("service=tipg") as tconn:
            if function:
                ok = tconn.execute("SELECT has_function_privilege(%s, 'EXECUTE')", (
                    tconn.execute("SELECT %s::regproc::oid", (locator,)).fetchone()[0],)).fetchone()[0]
                return ("ok", "function executable by tipg_ro") if ok else ("fail", "tipg_ro cannot execute it")
            schema, name = locator.split(".", 1)
            has_row = tconn.execute(f'SELECT EXISTS (SELECT 1 FROM "{schema}"."{name}")').fetchone()[0]
            return ("ok", "readable by tipg_ro, has rows") if has_row else ("warn", "readable but empty")
    except psycopg.errors.InsufficientPrivilege:
        return "fail", "tipg_ro is not allowed to read it"
    except psycopg.Error as e:
        return "fail", str(e).strip().splitlines()[0][:200]


def _mvt_features(data: bytes) -> int:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "0" / "0"
        p.mkdir(parents=True)
        f = p / "0.pbf"
        f.write_bytes(data)
        ds = gdal.OpenEx(f"MVT:{f}", gdal.OF_VECTOR)
        return sum(ds.GetLayer(i).GetFeatureCount() for i in range(ds.GetLayerCount()))


def check_tipg_collection(conn, locator: str) -> tuple[str, str]:
    status, body = _get(f"{TIPG}/collections/{locator}")
    if status != 200:
        return "fail", f"tiPG returned HTTP {status} for the collection (run make refresh?)"
    if _is_function(conn, locator):
        status, body = _get(f"{TIPG}/collections/{locator}/tiles/WebMercatorQuad/0/0/0")
        if status != 200:
            return "fail", f"tile 0/0/0 returned HTTP {status}"
        n = _mvt_features(body) if body else 0
        return ("ok", f"tile 0/0/0 has {n} features") if n else ("warn", "tile 0/0/0 is empty")
    status, body = _get(f"{TIPG}/collections/{locator}/items?limit=1")
    if status != 200:
        return "fail", f"items returned HTTP {status}"
    n = json.loads(body).get("numberReturned", 0)
    return ("ok", "collection served, returns features") if n else ("warn", "collection served but returned no features")


COG_ROOT = Path("/work/data/cog")
TITILER = "http://titiler:8000"


def check_cog(conn, locator: str) -> tuple[str, str]:
    path = COG_ROOT / f"{locator}.tif"
    if not path.exists():
        return "fail", "COG file is missing"
    try:
        info = gdal.Info(str(path), format="json")
    except RuntimeError as e:
        return "fail", f"GDAL cannot open it: {str(e)[:150]}"
    layout = (info.get("metadata", {}).get("IMAGE_STRUCTURE", {}) or {}).get("LAYOUT")
    size = info.get("size", [0, 0])
    return ("ok", f"valid COG, {size[0]} x {size[1]} px") if layout == "COG" else ("warn", "not a COG layout")


def _tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    import math
    n = 2 ** z
    lr = math.radians(lat)
    return int((lon + 180) / 360 * n), int((1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n)


def check_tile_url(conn, locator: str) -> tuple[str, str]:
    """titiler must render a tile and answer a point query at the raster's centre."""
    name = locator.removeprefix("/raster/").split("/{z}")[0]
    row = conn.execute("SELECT ST_X(ST_Centroid(footprint)), ST_Y(ST_Centroid(footprint)) FROM app.dataset_outputs "
                       "WHERE kind = 'cog' AND locator = %s", (name,)).fetchone()
    if not row or row[0] is None:
        return "unknown", "no COG footprint recorded"
    lon, lat = row
    x, y = _tile_xy(lon, lat, 7)
    status, body = _get(f"{TITILER}/cog/tiles/WebMercatorQuad/7/{x}/{y}.png?url=/data/cog/{name}.tif")
    if status != 200 or not body.startswith(b"\x89PNG"):
        return "fail", f"titiler tile returned HTTP {status}"
    status, body = _get(f"{TITILER}/cog/point/{lon:.5f},{lat:.5f}?url=/data/cog/{name}.tif")
    value = json.loads(body).get("values", [None])[0] if status == 200 else None
    return "ok", f"titiler tile z7 served; value at centre {value if value is None else round(value, 2)}"


CHECKS = {
    "postgis_table": check_postgis_table,
    "pub_view": check_pub_object,
    "tipg_collection": check_tipg_collection,
    "cog": check_cog,
    "tile_url": check_tile_url,
}


def check_outputs(conn, recipe: str | None = None) -> list[tuple[str, str, str, str]]:
    """Run checks; returns [(kind, locator, health, detail)]."""
    rows = conn.execute(
        "SELECT kind, locator FROM app.dataset_outputs WHERE (%s::text IS NULL OR recipe_name = %s) ORDER BY kind, locator",
        (recipe, recipe),
    ).fetchall()
    results = []
    for kind, locator in rows:
        check = CHECKS.get(kind)
        health, detail = check(conn, locator) if check else ("unknown", f"no check for {kind} yet")
        conn.execute(
            "UPDATE app.dataset_outputs SET health = %s, health_detail = %s, health_checked_at = now() WHERE kind = %s AND locator = %s",
            (health, detail, kind, locator),
        )
        results.append((kind, locator, health, detail))
    conn.commit()
    return results
