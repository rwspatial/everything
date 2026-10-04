"""Agricultural potential of one parcel: each soil map unit inside it scored on soil capability, farmland class,
slope, drainage and water storage, then limited by wetlands, flooding and land already built on or under water.
Method write-up: docs/methods/agricultural-potential.json (/admin/methods/agricultural-potential)."""
from __future__ import annotations

import json
import math
import os
import urllib.request

import geopandas as gpd
import shapely

METHOD_VERSION = 1

DESCRIPTOR = {
    "id": "py.agricultural_potential",
    "runtime": "python",
    "version": "1.0.0",
    "title": "Agricultural potential",
    "description": "How suitable a parcel is for farming: every soil map unit inside it scored 0-100 on soil "
                   "capability, farmland class, slope (30 m DEM), drainage and water storage (USDA SSURGO), limited "
                   "by wetlands (NWI), flooding and land already built on (Cropland Data Layer 2025). The report adds "
                   "current land use, hardiness zone, elevation and FEMA flood zones.",
    "units": ["parcel"],
    "method": "agricultural-potential",
    "inputs": {
        "unit": {"type": "enum", "title": "Unit", "values": ["parcel"], "default": "parcel", "required": True},
        "place": {"type": "string", "title": "Parcel", "required": True,
                  "description": "The parcel's unit_key (pub.units__parcel)"},
    },
    "outputs": {"layer": {"type": "vector-layer", "geometry": "MultiPolygon",
                          "fields": ["soil", "score", "class", "limits", "acres"]},
                "report": {"type": "json"}},
    "resources": {"cpu": 1, "memoryMb": 1024, "timeoutSec": 600},
}

TITILER = os.environ.get("TITILER_URL", "http://titiler:8000")
COG_ROOT = os.environ.get("COG_ROOT", "/data/cog").rstrip("/")
ACRE = 4046.8564224
MAX_PIECES_FOR_RASTER = 80  # above this, slope comes from SSURGO and land cover only from the parcel as a whole

# ---- factor scores (0-100) -------------------------------------------------------------------------------------
WEIGHTS = {"capability": 0.30, "farmland": 0.20, "slope": 0.20, "drainage": 0.15, "water": 0.15}
CAPABILITY = {"1": 100, "2": 85, "3": 65, "4": 45, "5": 25, "6": 15, "7": 5, "8": 0}
FARMLAND = {"All areas are prime farmland": 100, "Farmland of statewide importance": 75,
            "Farmland of local importance": 55, "Not prime farmland": 20}
DRAINAGE = {"Well drained": 100, "Moderately well drained": 100, "Somewhat excessively drained": 70,
            "Excessively drained": 45, "Somewhat poorly drained": 55, "Poorly drained": 20, "Very poorly drained": 0}
SLOPE_PTS = [(0, 100), (3, 100), (8, 85), (15, 55), (25, 15), (35, 0)]       # percent slope -> score
WATER_PTS = [(0, 10), (5, 25), (10, 55), (15, 80), (20, 100)]                 # cm in the top 150 cm -> score
FLOODING = {"Very frequent": 0.5, "Frequent": 0.5, "Occasional": 0.8, "Rare": 0.95, "None": 1.0}
CLASSES = [(70, "High", "#006d2c"), (55, "Good", "#31a354"), (40, "Moderate", "#74c476"),
           (20, "Limited", "#c7e9c0"), (0, "Unsuitable", "#d9d9d9")]
FACTOR_LABELS = {"capability": "soil capability", "farmland": "farmland class", "slope": "slope",
                 "drainage": "drainage", "water": "water storage"}

# USDA Cropland Data Layer 2025 classes found in Maine (same labels as the maine-landcover map).
CDL = {1: 'Corn', 4: 'Sorghum', 5: 'Soybeans', 6: 'Sunflower', 12: 'Sweet corn', 21: 'Barley', 23: 'Spring wheat',
       24: 'Winter wheat', 27: 'Rye', 28: 'Oats', 30: 'Speltz', 35: 'Mustard', 36: 'Alfalfa',
       37: 'Other hay / non-alfalfa', 39: 'Buckwheat', 41: 'Sugar beets', 42: 'Dry beans', 43: 'Potatoes',
       47: 'Misc. vegetables and fruits', 58: 'Clover / wildflowers', 59: 'Sod / grass seed',
       61: 'Fallow / idle cropland', 68: 'Apples', 69: 'Grapes', 70: 'Christmas trees', 71: 'Other tree crops',
       77: 'Pears', 92: 'Aquaculture', 111: 'Open water', 121: 'Developed, open space',
       122: 'Developed, low intensity', 123: 'Developed, medium intensity', 124: 'Developed, high intensity',
       131: 'Barren', 141: 'Deciduous forest', 142: 'Evergreen forest', 143: 'Mixed forest', 152: 'Shrubland',
       176: 'Grass / pasture', 190: 'Woody wetlands', 195: 'Herbaceous wetlands', 206: 'Carrots', 208: 'Garlic',
       214: 'Broccoli', 220: 'Plums', 221: 'Strawberries', 242: 'Blueberries', 244: 'Cauliflower', 246: 'Radishes'}
BUILT_OR_WATER = {111, 122, 123, 124}  # developed open space (lawns, playing fields) stays farmable
FOREST = {141, 142, 143}
FARMED = {c for c in CDL if c < 100 or c in (176, 206, 208, 214, 220, 221, 242, 244, 246)} - {92}


def interp(points: list[tuple[float, float]], x: float) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def classify(score: float) -> tuple[str, str]:
    for cut, name, color in CLASSES:
        if score >= cut:
            return name, color
    return CLASSES[-1][1], CLASSES[-1][2]


def zonal(geom, cog: str, categorical: bool = False) -> dict | None:
    """titiler statistics of one COG over a polygon (EPSG:4326); None when no pixel centre falls inside."""
    url = f"{TITILER}/cog/statistics?url={COG_ROOT}/{cog}.tif" + ("&categorical=true" if categorical else "")
    body = json.dumps({"type": "Feature", "properties": {}, "geometry": shapely.geometry.mapping(geom)}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            s = json.load(r)["properties"]["statistics"]["b1"]
    except Exception:  # noqa: BLE001  a sliver with no pixel, or a COG missing: the factor is left out
        return None
    return s if s.get("valid_pixels", s.get("count", 0)) else None


def cover(stats: dict | None) -> dict[int, float]:
    """Categorical statistics -> {class: share 0-1}."""
    if not stats:
        return {}
    counts, values = stats["histogram"]
    total = sum(counts) or 1
    return {int(v): c / total for c, v in zip(counts, values) if c}


def run(ctx, inputs: dict) -> dict:
    key = inputs["place"]
    ctx.progress(0.05, "reading the parcel")
    parcel = ctx.conn.execute(
        """SELECT name, short_name, county_name, ST_Area(geom::geography) / %s AS acres, ST_AsBinary(geom) AS wkb
           FROM pub.units__parcel WHERE unit_key = %s""", (ACRE, key)).fetchone()
    if not parcel:
        raise ValueError(f"no parcel with key {key!r}")
    name, short_name, county, parcel_acres, wkb = parcel
    pgeom = shapely.from_wkb(bytes(wkb))

    ctx.progress(0.1, "soils, wetlands and flooding")
    # One piece per soil map unit (SSURGO) inside the parcel, with the share of it in NWI wetlands.
    rows = ctx.conn.execute(
        """WITH p AS (SELECT geom FROM pub.units__parcel WHERE unit_key = %(key)s),
                s AS (SELECT u.mukey, ST_Union(ST_Intersection(u.geom, p.geom)) AS g
                      FROM src_ssurgo.mupolygon u, p WHERE u.geom && p.geom AND ST_Intersects(u.geom, p.geom)
                      GROUP BY u.mukey),
                pieces AS (SELECT mukey, ST_Multi(ST_CollectionExtract(g, 3)) AS g FROM s)
           SELECT x.mukey, m.muname, m.farmlndcl, m.niccdcd, m.drclassdcd, m.slopegraddcp::float8, m.aws0150wta::float8,
                  m.flodfreqdcd, ST_Area(x.g::geography) / %(acre)s AS acres,
                  coalesce((SELECT ST_Area(ST_Intersection(x.g, ST_Union(w.geom))::geography) FROM src_nwi.wetlands w
                            WHERE w.geom && x.g AND ST_Intersects(w.geom, x.g)), 0) / nullif(ST_Area(x.g::geography), 0) AS wet,
                  ST_AsBinary(x.g) AS wkb
           FROM pieces x JOIN src_ssurgo.mapunit m USING (mukey)
           WHERE NOT ST_IsEmpty(x.g) AND ST_Area(x.g::geography) > 1
           ORDER BY acres DESC""", {"key": key, "acre": ACRE}).fetchall()
    if not rows:
        raise ValueError(f"no SSURGO soil data inside parcel {key} ({name})")

    use_raster = len(rows) <= MAX_PIECES_FOR_RASTER
    pieces = []
    for i, (mukey, muname, farm, cap, drain, ssurgo_slope, water, flood, acres, wet, gw) in enumerate(rows):
        ctx.progress(0.15 + 0.6 * i / len(rows), f"scoring soil {i + 1} of {len(rows)}")
        g = shapely.from_wkb(bytes(gw))
        slope_stats = zonal(g, "maine/slope_30m") if use_raster else None
        # The slope COG is in degrees; the scores (and SSURGO) use percent.
        slope_pct = math.tan(math.radians(slope_stats["mean"])) * 100 if slope_stats else ssurgo_slope
        lc = cover(zonal(g, "maine/cdl_2025", categorical=True)) if use_raster else {}
        built = sum(v for c, v in lc.items() if c in BUILT_OR_WATER)
        factors = {
            "capability": CAPABILITY.get(str(cap)) if cap is not None else None,
            "farmland": FARMLAND.get(farm),
            "slope": interp(SLOPE_PTS, slope_pct) if slope_pct is not None else None,
            "drainage": DRAINAGE.get(drain),
            "water": interp(WATER_PTS, water) if water is not None else None,
        }
        known = {k: v for k, v in factors.items() if v is not None}
        base = (sum(WEIGHTS[k] * v for k, v in known.items()) / sum(WEIGHTS[k] for k in known)) if known else 0.0
        wet = min(max(wet or 0.0, 0.0), 1.0)
        flood_mult = FLOODING.get(flood or "None", 1.0)
        score = base * (1 - wet) * flood_mult * (1 - built)
        # What holds the score down: the weakest factor (if below 60) and any constraint that applies.
        limits = []
        if known:
            k_low = min(known, key=known.get)
            if known[k_low] < 60:
                limits.append(f"{FACTOR_LABELS[k_low]} ({round(known[k_low])})")
        if wet >= 0.1:
            limits.append(f"wetland ({round(wet * 100)} %)")
        if flood_mult < 1:
            limits.append(f"flooding ({flood.lower()})")
        if built >= 0.1:
            limits.append(f"built or water ({round(built * 100)} %)")
        cls, _ = classify(score)
        pieces.append({
            "id": i + 1, "soil": muname, "mukey": str(mukey), "score": round(score), "class": cls,
            "limits": ", ".join(limits) or "none", "acres": round(acres, 2),
            "capability": f"Class {cap}" if cap else None, "farmland": farm, "drainage": drain,
            "slope_pct": round(slope_pct, 1) if slope_pct is not None else None,
            "water_cm": round(water, 1) if water is not None else None,
            "wetland_pct": round(wet * 100), "flooding": flood, "built_pct": round(built * 100),
            "factors": {k: (round(v) if v is not None else None) for k, v in factors.items()},
            "geometry": g,
        })

    ctx.progress(0.8, "parcel context")
    total = sum(p["acres"] for p in pieces) or 1
    wavg = lambda f: sum(f(p) * p["acres"] for p in pieces) / total  # noqa: E731
    overall = wavg(lambda p: p["score"])
    cls, color = classify(overall)
    by_class = {name: round(sum(p["acres"] for p in pieces if p["class"] == name), 2) for _, name, _ in CLASSES}
    factor_means = {}
    for k in WEIGHTS:
        have = [p for p in pieces if p["factors"][k] is not None]
        a = sum(p["acres"] for p in have)
        factor_means[k] = round(sum(p["factors"][k] * p["acres"] for p in have) / a) if a else None

    land = cover(zonal(pgeom, "maine/cdl_2025", categorical=True))
    land_use = sorted(({"class": CDL.get(c, f"CDL class {c}"), "code": c, "pct": round(v * 100, 1)}
                       for c, v in land.items()), key=lambda r: -r["pct"])
    elev = zonal(pgeom, "maine/dem_10m") or zonal(pgeom, "maine/dem_30m")
    zone = ctx.conn.execute(
        """SELECT z.zone FROM pub.maine_lands__hardiness_zones z, pub.units__parcel p
           WHERE p.unit_key = %s AND ST_Intersects(z.geom, ST_PointOnSurface(p.geom)) LIMIT 1""", (key,)).fetchone()
    sfha = ctx.conn.execute(
        """SELECT coalesce(sum(ST_Area(ST_Intersection(f.geom, p.geom)::geography)), 0) / ST_Area(p.geom::geography)
           FROM pub.units__parcel p LEFT JOIN src_fema.flood_zones f
             ON f.geom && p.geom AND ST_Intersects(f.geom, p.geom) AND f.sfha_tf = 'T'
           WHERE p.unit_key = %s GROUP BY p.geom""", (key,)).fetchone()

    ctx.progress(0.9, "writing")
    gdf = gpd.GeoDataFrame([{k: v for k, v in p.items() if k != "factors"} for p in pieces], geometry="geometry",
                           crs="EPSG:4326")
    cols = {"soil": "text", "mukey": "text", "score": "integer", "class": "text", "limits": "text",
            "acres": "double precision", "capability": "text", "farmland": "text", "drainage": "text",
            "slope_pct": "double precision", "water_cm": "double precision", "wetland_pct": "integer",
            "flooding": "text", "built_pct": "integer"}
    n = ctx.write_layer(gdf, cols)
    present = [(name, col) for _, name, col in CLASSES if by_class[name] > 0]
    return {
        "rows": n,
        "title": f"Agricultural potential: {short_name}",
        "properties": list(cols),
        "style": {"kind": "maplibre", "layers": [
            {"type": "fill", "paint": {"fill-color": ["match", ["get", "class"], *[x for c in present for x in c], "#d9d9d9"],
                                       "fill-opacity": 0.75}},
            {"type": "line", "paint": {"line-color": "#ffffff", "line-width": 1}}]},
        "legend": {"type": "categorical", "title": "Agricultural potential (soil map units)",
                   "items": [{"label": name, "color": col} for name, col in present]},
        "popup": "{soil}: {class} ({score}/100); limits: {limits}",
        "report": {
            "method": {"id": "agricultural-potential", "version": METHOD_VERSION},
            "parcel": {"key": key, "name": name, "county": county, "acres": round(parcel_acres, 2)},
            "score": round(overall), "class": cls, "color": color,
            "acres_by_class": by_class,
            "factors": factor_means, "weights": WEIGHTS,
            "soils": [{k: p[k] for k in ("soil", "acres", "score", "class", "limits", "capability", "farmland",
                                         "drainage", "slope_pct", "water_cm", "wetland_pct", "flooding")}
                      for p in pieces],
            "land_use": land_use[:8],
            "farmed_pct": round(sum(v for c, v in land.items() if c in FARMED) * 100, 1),
            "forest_pct": round(sum(v for c, v in land.items() if c in FOREST) * 100, 1),
            "hardiness_zone": zone[0] if zone else None,
            "elevation_ft": ({"min": round(elev["min"] * 3.28084), "mean": round(elev["mean"] * 3.28084),
                              "max": round(elev["max"] * 3.28084)} if elev else None),
            "fema_flood_zone_pct": round((sfha[0] or 0) * 100, 1) if sfha else 0.0,
            "wetland_pct": round(wavg(lambda p: p["wetland_pct"])),
            "slope_source": "30 m DEM" if use_raster else "SSURGO representative slope (many soil units)",
        },
    }
