"""Wildfire fuel hazard of one parcel: LANDFIRE 40 Scott & Burgan fire behavior fuel models (FBFM40) inside the parcel,
each rated from its fire behavior (flame length, rate of spread) and raised on steep slopes, blended with the fuels in
a 500 m ring around it; plus the buildings exposed. Method: docs/methods/fire-risk.json (/admin/methods/fire-risk)."""
from __future__ import annotations

import io
import json
import math
import os
import urllib.request

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features
import shapely
from shapely.ops import unary_union

METHOD_VERSION = 1

DESCRIPTOR = {
    "id": "py.fire_risk",
    "runtime": "python",
    "version": "1.0.0",
    "title": "Wildfire fuel hazard",
    "description": "How much fire the vegetation on and around a parcel could carry: LANDFIRE fire behavior fuel models "
                   "(Scott & Burgan 40, 30 m) rated by flame length and rate of spread, raised on steep slopes, blended "
                   "with the fuels within 500 m; the report adds the fuel types present and the buildings within 100 ft "
                   "of high-hazard fuel. A fuel hazard, not a probability of fire.",
    "units": ["parcel"],
    "method": "fire-risk",
    "inputs": {
        "unit": {"type": "enum", "title": "Unit", "values": ["parcel"], "default": "parcel", "required": True},
        "place": {"type": "string", "title": "Parcel", "required": True,
                  "description": "The parcel's unit_key (pub.units__parcel)"},
    },
    "outputs": {"layer": {"type": "vector-layer", "geometry": "MultiPolygon",
                          "fields": ["fuel_model", "fuel_name", "hazard", "class", "acres"]},
                "report": {"type": "json"}},
    "resources": {"cpu": 1, "memoryMb": 1024, "timeoutSec": 600},
}

TITILER = os.environ.get("TITILER_URL", "http://titiler:8000")
COG_ROOT = os.environ.get("COG_ROOT", "/data/cog").rstrip("/")
FUELS_COG = "maine/landfire_fbfm40"
UTM = 26919
ACRE = 4046.8564224
RING_M = 500          # surroundings: ember and fire-approach exposure
HIZ_M = 30.48         # home ignition zone: 100 ft around a building (Firewise / NFPA 1144)
W_PARCEL, W_RING = 0.65, 0.35
W_FLAME, W_SPREAD = 0.6, 0.4

# Scott & Burgan (2005) fuel models: code -> (short name, description, rate of spread rating, flame length rating).
# Ratings are the guide's qualitative fire behavior under its standard (dry) conditions.
VL, L, M, H, VH, X = "very low", "low", "moderate", "high", "very high", "extreme"
RATING = {VL: 5, L: 20, M: 45, H: 70, VH: 85, X: 100}
NONBURN = {91: ("NB1", "Urban or developed"), 92: ("NB2", "Snow or ice"), 93: ("NB3", "Agricultural"),
           98: ("NB8", "Open water"), 99: ("NB9", "Bare ground")}
FUELS = {
    101: ("GR1", "Short, sparse dry-climate grass", M, L), 102: ("GR2", "Low-load dry-climate grass", H, M),
    103: ("GR3", "Low-load, very coarse humid-climate grass", H, M), 104: ("GR4", "Moderate-load dry-climate grass", VH, H),
    105: ("GR5", "Low-load humid-climate grass", VH, H), 106: ("GR6", "Moderate-load humid-climate grass", VH, H),
    107: ("GR7", "High-load dry-climate grass", VH, VH), 108: ("GR8", "High-load, very coarse humid-climate grass", VH, VH),
    109: ("GR9", "Very high-load humid-climate grass", X, X),
    121: ("GS1", "Low-load dry-climate grass-shrub", M, L), 122: ("GS2", "Moderate-load dry-climate grass-shrub", H, M),
    123: ("GS3", "Moderate-load humid-climate grass-shrub", H, M), 124: ("GS4", "High-load humid-climate grass-shrub", H, VH),
    141: ("SH1", "Low-load dry-climate shrub", VL, VL), 142: ("SH2", "Moderate-load dry-climate shrub", L, L),
    143: ("SH3", "Moderate-load humid-climate shrub", L, L), 144: ("SH4", "Low-load humid-climate timber-shrub", H, M),
    145: ("SH5", "High-load dry-climate shrub", VH, VH), 146: ("SH6", "Low-load humid-climate shrub", H, H),
    147: ("SH7", "Very high-load dry-climate shrub", VH, VH), 148: ("SH8", "High-load humid-climate shrub", H, H),
    149: ("SH9", "Very high-load humid-climate shrub", VH, VH),
    161: ("TU1", "Low-load dry-climate timber-grass-shrub", L, L), 162: ("TU2", "Moderate-load humid-climate timber-shrub", M, L),
    163: ("TU3", "Moderate-load humid-climate timber-grass-shrub", H, M), 164: ("TU4", "Dwarf conifer with understory", M, M),
    165: ("TU5", "Very high-load dry-climate timber-shrub", M, M),
    181: ("TL1", "Low-load compact conifer litter", VL, VL), 182: ("TL2", "Low-load broadleaf litter", VL, VL),
    183: ("TL3", "Moderate-load conifer litter", VL, L), 184: ("TL4", "Small downed logs", L, L),
    185: ("TL5", "High-load conifer litter", L, L), 186: ("TL6", "Moderate-load broadleaf litter", M, L),
    187: ("TL7", "Large downed logs", L, L), 188: ("TL8", "Long-needle litter", M, L),
    189: ("TL9", "Very high-load broadleaf litter", M, M),
    201: ("SB1", "Low-load activity fuel (slash)", L, L), 202: ("SB2", "Moderate-load activity fuel or low-load blowdown", M, M),
    203: ("SB3", "High-load activity fuel or moderate-load blowdown", H, H), 204: ("SB4", "High-load blowdown", H, H),
}
CLASSES = [(75, "Very high", "#b30000"), (55, "High", "#e34a33"), (35, "Moderate", "#fc8d59"),
           (15, "Low", "#fdcc8a"), (0, "Very low", "#fef0d9")]
NONBURN_CLASS = ("Non-burnable", "#d9d9d9")


def fuel_hazard(code: int) -> float:
    """0-100 from the fuel model's flame length and rate of spread ratings; non-burnable (and unknown) is 0."""
    f = FUELS.get(code)
    return W_FLAME * RATING[f[3]] + W_SPREAD * RATING[f[2]] if f else 0.0


def fuel_label(code: int) -> tuple[str, str]:
    if code in FUELS:
        return FUELS[code][0], FUELS[code][1]
    return NONBURN.get(code, (str(code), f"LANDFIRE class {code}"))


def slope_multiplier(slope_deg: float | None) -> float:
    """Fire spreads faster upslope: a simplified Rothermel slope factor, 1 + 2·tan²(slope), capped at 1.6."""
    if slope_deg is None:
        return 1.0
    return min(1.0 + 2.0 * math.tan(math.radians(slope_deg)) ** 2, 1.6)


def classify(score: float, burnable: bool = True) -> tuple[str, str]:
    if not burnable:
        return NONBURN_CLASS
    for cut, name, color in CLASSES:
        if score >= cut:
            return name, color
    return CLASSES[-1][1], CLASSES[-1][2]


def _feature(geom) -> bytes:
    return json.dumps({"type": "Feature", "properties": {}, "geometry": shapely.geometry.mapping(geom)}).encode()


def zonal(geom, cog: str, categorical: bool = False) -> dict | None:
    """titiler statistics of a COG over a polygon (EPSG:4326); None when no pixel centre falls inside."""
    url = f"{TITILER}/cog/statistics?url={COG_ROOT}/{cog}.tif" + ("&categorical=true" if categorical else "")
    try:
        req = urllib.request.Request(url, data=_feature(geom), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            s = json.load(r)["properties"]["statistics"]["b1"]
    except Exception:  # noqa: BLE001  a sliver with no pixel, or a COG missing
        return None
    return s if s.get("valid_pixels", s.get("count", 0)) else None


def fuel_pixels(geom) -> tuple[np.ma.MaskedArray, object]:
    """The fuel model raster clipped to a polygon (EPSG:4326 in), at its native 30 m in UTM 19N."""
    url = f"{TITILER}/cog/feature.tif?url={COG_ROOT}/{FUELS_COG}.tif&dst_crs=epsg:{UTM}&max_size=4096"
    req = urllib.request.Request(url, data=_feature(geom), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    with rasterio.open(io.BytesIO(data)) as ds:
        return ds.read(1, masked=True), ds.transform


def run(ctx, inputs: dict) -> dict:
    key = inputs["place"]
    ctx.progress(0.05, "reading the parcel")
    row = ctx.conn.execute(
        """SELECT name, short_name, county_name, ST_Area(geom::geography) / %s, ST_AsBinary(ST_Transform(geom, %s))
           FROM pub.units__parcel WHERE unit_key = %s""", (ACRE, UTM, key)).fetchone()
    if not row:
        raise ValueError(f"no parcel with key {key!r}")
    name, short_name, county, parcel_acres, wkb_utm = row
    parcel_utm = shapely.from_wkb(bytes(wkb_utm)).buffer(0)
    to_wgs = lambda g: gpd.GeoSeries([g], crs=f"EPSG:{UTM}").to_crs(4326).iloc[0]  # noqa: E731

    # 1. Fuels on the parcel: the raster (clipped to the parcel plus one pixel) polygonized by fuel model, then cut
    #    to the parcel's exact outline.
    ctx.progress(0.15, "fuels on the parcel")
    arr, transform = fuel_pixels(to_wgs(parcel_utm.buffer(31)))
    shapes = rasterio.features.shapes(arr.filled(-9999).astype("int32"), mask=~np.ma.getmaskarray(arr), transform=transform)
    by_code: dict[int, list] = {}
    for geom, value in shapes:
        by_code.setdefault(int(value), []).append(shapely.geometry.shape(geom))
    if not by_code:
        raise ValueError(f"no LANDFIRE fuel data inside parcel {key} ({name})")

    ctx.progress(0.35, "slope")
    pieces = []
    for code, polys in sorted(by_code.items()):
        g = unary_union(polys).intersection(parcel_utm)
        if g.is_empty or g.area < 1:
            continue
        g_wgs = to_wgs(g)
        burnable = code in FUELS
        slope = zonal(g_wgs, "maine/slope_30m") if burnable else None
        mult = slope_multiplier(slope["mean"] if slope else None)
        hazard = min(fuel_hazard(code) * mult, 100.0)
        cls, _ = classify(hazard, burnable)
        short, desc = fuel_label(code)
        f = FUELS.get(code)
        pieces.append({"code": code, "fuel_model": short, "fuel_name": desc, "hazard": round(hazard), "class": cls,
                       "spread": f[2] if f else None, "flame": f[3] if f else None,
                       "slope_deg": round(slope["mean"], 1) if slope else None, "slope_factor": round(mult, 2),
                       "acres": round(g.area / ACRE, 2), "geom_utm": g, "geometry": g_wgs})
    total = sum(p["acres"] for p in pieces) or 1
    on_parcel = sum(p["hazard"] * p["acres"] for p in pieces) / total

    # 2. Surroundings: fuels in a 500 m ring outside the parcel (categorical statistics).
    ctx.progress(0.6, "fuels within 500 m")
    ring = parcel_utm.buffer(RING_M).difference(parcel_utm)
    stats = zonal(to_wgs(ring), FUELS_COG, categorical=True)
    ring_cover: dict[int, float] = {}
    if stats:
        counts, values = stats["histogram"]
        n = sum(counts) or 1
        ring_cover = {int(v): c / n for c, v in zip(counts, values) if c}
    ring_hazard = sum(fuel_hazard(c) * share for c, share in ring_cover.items()) if ring_cover else on_parcel

    score = W_PARCEL * on_parcel + W_RING * ring_hazard
    cls, color = classify(score)

    # 3. Exposure: buildings on the parcel, and those within 100 ft of high or very high hazard fuel on it.
    ctx.progress(0.75, "buildings")
    bld = [shapely.from_wkb(bytes(b)) for (b,) in ctx.conn.execute(
        """SELECT ST_AsBinary(ST_Transform(b.geom, %s)) FROM src_overture.buildings b, pub.units__parcel p
           WHERE p.unit_key = %s AND b.geom && p.geom AND ST_Intersects(b.geom, p.geom)""", (UTM, key)).fetchall()]
    hot = unary_union([p["geom_utm"] for p in pieces if p["class"] in ("High", "Very high")]) if pieces else None
    exposed = sum(1 for b in bld if hot is not None and not hot.is_empty and b.distance(hot) <= HIZ_M)

    ctx.progress(0.9, "writing")
    gdf = gpd.GeoDataFrame([{"id": i + 1, **{k: v for k, v in p.items() if k not in ("geom_utm", "code")}}
                            for i, p in enumerate(pieces)], geometry="geometry", crs="EPSG:4326")
    cols = {"fuel_model": "text", "fuel_name": "text", "hazard": "integer", "class": "text", "spread": "text",
            "flame": "text", "slope_deg": "double precision", "slope_factor": "double precision", "acres": "double precision"}
    n = ctx.write_layer(gdf, cols)
    order = [c[1] for c in CLASSES] + [NONBURN_CLASS[0]]
    colors = {c[1]: c[2] for c in CLASSES} | {NONBURN_CLASS[0]: NONBURN_CLASS[1]}
    by_class = {c: round(sum(p["acres"] for p in pieces if p["class"] == c), 2) for c in order}
    present = [(c, colors[c]) for c in order if by_class[c] > 0]
    fuels = sorted(({"fuel_model": p["fuel_model"], "fuel_name": p["fuel_name"], "acres": p["acres"], "hazard": p["hazard"],
                     "class": p["class"], "spread": p["spread"], "flame": p["flame"]} for p in pieces), key=lambda r: -r["acres"])
    ring_top = sorted(({"fuel_model": fuel_label(c)[0], "fuel_name": fuel_label(c)[1], "pct": round(s * 100, 1),
                        "hazard": round(fuel_hazard(c))} for c, s in ring_cover.items()), key=lambda r: -r["pct"])[:6]
    slopes = [p["slope_deg"] for p in pieces if p["slope_deg"] is not None]
    return {
        "rows": n,
        "title": f"Wildfire fuel hazard: {short_name}",
        "properties": list(cols),
        "style": {"kind": "maplibre", "layers": [
            {"type": "fill", "paint": {"fill-color": ["match", ["get", "class"], *[x for c in present for x in c], "#d9d9d9"],
                                       "fill-opacity": 0.75}},
            {"type": "line", "paint": {"line-color": "#ffffff", "line-width": 0.8}}]},
        "legend": {"type": "categorical", "title": "Wildfire fuel hazard (LANDFIRE fuel models)",
                   "items": [{"label": c, "color": col} for c, col in present]},
        "popup": "{fuel_model} {fuel_name}: {class} ({hazard}/100)",
        "report": {
            "method": {"id": "fire-risk", "version": METHOD_VERSION},
            "parcel": {"key": key, "name": name, "county": county, "acres": round(parcel_acres, 2)},
            "score": round(score), "class": cls, "color": color,
            "on_parcel": round(on_parcel), "surroundings": round(ring_hazard),
            "weights": {"parcel": W_PARCEL, "surroundings": W_RING},
            "acres_by_class": by_class,
            "fuels": fuels,
            "surrounding_fuels": ring_top,
            "burnable_pct": round(100 * sum(p["acres"] for p in pieces if p["code"] in FUELS) / total, 1),
            "buildings": len(bld), "buildings_near_high_hazard": exposed,
            "slope_deg": {"max": max(slopes), "mean": round(sum(slopes) / len(slopes), 1)} if slopes else None,
        },
    }
