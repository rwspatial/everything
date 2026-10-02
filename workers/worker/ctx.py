"""What a Python process gets: its inputs, reading a pub collection, writing its output layer, progress."""
from __future__ import annotations

import json
import os
import re

import geopandas as gpd
import psycopg
import shapely
from psycopg import sql

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class Ctx:
    def __init__(self) -> None:
        self.job_id = int(os.environ["JOB_ID"])
        self.inputs = json.loads(os.environ["JOB_INPUTS"])
        self.table = f"job_{self.job_id}"
        self.conn = psycopg.connect(os.environ["WORKER_DATABASE_URL"], autocommit=True)

    def progress(self, fraction: float, message: str = "") -> None:
        self.conn.execute("UPDATE app.jobs SET progress = %s, progress_message = %s WHERE id = %s",
                          (max(0.0, min(1.0, fraction)), message[:200], self.job_id))

    def geometry_column(self, collection: str) -> tuple[str, str, int]:
        schema, name = collection.split(".", 1)
        row = self.conn.execute(
            """SELECT a.attname, postgis_typmod_type(a.atttypmod), postgis_typmod_srid(a.atttypmod)
               FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
               WHERE c.relnamespace = %s::regnamespace AND c.relname = %s AND a.atttypid = 'geometry'::regtype
                 AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum LIMIT 1""", (schema, name)).fetchone()
        if not row:
            raise ValueError(f"{collection} has no geometry column")
        return row

    def read_collection(self, collection: str, fields: list[str]) -> gpd.GeoDataFrame:
        """id, the given fields and the geometry (as `geometry`) of a pub view, in its own SRID."""
        if not re.match(r"^pub\.[a-z0-9_]+$", collection) or not all(IDENT.match(f) for f in fields):
            raise ValueError("bad collection or field name")
        gcol, _gtype, srid = self.geometry_column(collection)
        schema, name = collection.split(".", 1)
        cols = sql.SQL(", ").join(sql.Identifier(f) for f in dict.fromkeys(fields))
        q = sql.SQL("SELECT id, {cols}, ST_AsBinary({g}) AS wkb FROM {t} WHERE {g} IS NOT NULL ORDER BY id").format(
            cols=cols, g=sql.Identifier(gcol), t=sql.Identifier(schema, name))
        cur = self.conn.execute(q)
        names = [d.name for d in cur.description]
        rows = cur.fetchall()
        data = {n: [r[i] for r in rows] for i, n in enumerate(names) if n != "wkb"}
        geoms = shapely.from_wkb([bytes(r[names.index("wkb")]) for r in rows])
        return gpd.GeoDataFrame(data, geometry=geoms, crs=f"EPSG:{srid}")

    def write_layer(self, gdf: gpd.GeoDataFrame, columns: dict[str, str]) -> int:
        """Write ml_out.job_<id>: id + `columns` ({name: SQL type}) + geom (typed, SRID kept), with a GiST index."""
        srid = gdf.crs.to_epsg()
        types = set(gdf.geometry.geom_type)
        gtype = ("MultiPolygon" if types <= {"Polygon", "MultiPolygon"} else
                 "MultiLineString" if types <= {"LineString", "MultiLineString"} else
                 "Point" if types == {"Point"} else "Geometry")
        multi = gtype.startswith("Multi")
        t = sql.Identifier("ml_out", self.table)
        coldefs = sql.SQL(", ").join(sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(typ)) for c, typ in columns.items())
        with self.conn.transaction():
            self.conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(t))
            self.conn.execute(sql.SQL("CREATE TABLE {} (id integer PRIMARY KEY, {}, geom geometry({}, {}))").format(
                t, coldefs, sql.SQL(gtype), sql.Literal(srid)))
            geom_sql = "ST_Multi(ST_GeomFromWKB(%s, {srid}))" if multi else "ST_GeomFromWKB(%s, {srid})"
            ins = sql.SQL("INSERT INTO {} (id, {}, geom) VALUES (%s, {}, " + geom_sql.format(srid=int(srid)) + ")").format(
                t, sql.SQL(", ").join(sql.Identifier(c) for c in columns), sql.SQL(", ").join(sql.Placeholder() for _ in columns))
            with self.conn.cursor() as cur:
                cur.executemany(ins, [
                    (int(r["id"]), *[None if _isnull(r[c]) else _py(r[c]) for c in columns], shapely.to_wkb(r.geometry))
                    for _, r in gdf.iterrows()])
            self.conn.execute(sql.SQL("CREATE INDEX ON {} USING gist (geom)").format(t))
            self.conn.execute(sql.SQL("ANALYZE {}").format(t))
        return len(gdf)


def _isnull(v) -> bool:
    try:
        return v is None or v != v  # NaN
    except Exception:
        return False


def _py(v):
    return v.item() if hasattr(v, "item") else v


def emit(result: dict) -> None:
    """The child's last stdout line: the worker reads it as the job result."""
    print("RESULT " + json.dumps(result, default=float), flush=True)
