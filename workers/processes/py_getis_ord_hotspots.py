"""Getis-Ord Gi* hot and cold spots (PySAL esda) of a numeric field."""
from __future__ import annotations

import libpysal
import numpy as np
from esda.getisord import G_Local

DESCRIPTOR = {
    "id": "py.getis_ord_hotspots",
    "runtime": "python",
    "version": "1.0.0",
    "title": "Hot spots (Getis-Ord Gi*)",
    "description": "Where high or low values of a numeric field cluster: Gi* z-scores with permutation p-values "
                   "(999 permutations), classed at 90/95/99 % confidence.",
    "inputs": {
        "collection": {"type": "collection-ref", "title": "Layer", "required": True,
                       "geometry": ["Polygon", "MultiPolygon", "Point", "MultiPoint"]},
        "field": {"type": "field-ref", "title": "Numeric field", "of": "collection", "dtype": "numeric", "required": True},
        "label": {"type": "field-ref", "title": "Label field (popups)", "of": "collection", "dtype": "any", "required": False},
        "weights": {"type": "enum", "title": "Neighbours", "values": ["queen", "knn"], "default": "queen",
                    "description": "queen: polygons sharing an edge or corner; knn: the k nearest (points need knn)"},
        "k": {"type": "integer", "title": "k (knn only)", "default": 8, "minimum": 2, "maximum": 30, "when": {"weights": "knn"}},
    },
    "outputs": {"layer": {"type": "vector-layer", "geometry": "same-as-input",
                          "fields": ["label", "value", "gi_z", "gi_p", "cluster"]},
                "report": {"type": "json"}},
    "resources": {"cpu": 1, "memoryMb": 2048, "timeoutSec": 900},
}

CLASSES = [("Hot spot, 99 % confidence", "#b2182b"), ("Hot spot, 95 % confidence", "#ef8a62"),
           ("Hot spot, 90 % confidence", "#fddbc7"), ("Not significant", "#f0f0f0"),
           ("Cold spot, 90 % confidence", "#d1e5f0"), ("Cold spot, 95 % confidence", "#67a9cf"),
           ("Cold spot, 99 % confidence", "#2166ac")]


def classify(z: float, p: float) -> str:
    for cut, conf in ((0.01, "99"), (0.05, "95"), (0.10, "90")):
        if p < cut:
            return f"{'Hot' if z > 0 else 'Cold'} spot, {conf} % confidence"
    return "Not significant"


def run(ctx, inputs: dict) -> dict:
    field, label = inputs["field"], inputs.get("label") or None
    ctx.progress(0.05, "reading")
    gdf = ctx.read_collection(inputs["collection"], [field] + ([label] if label else []))
    total = len(gdf)
    gdf = gdf[gdf[field].notna()].reset_index(drop=True)
    y = gdf[field].astype(float).to_numpy()
    ctx.progress(0.2, "building neighbours")
    weights = inputs.get("weights", "queen")
    points = set(gdf.geometry.geom_type) <= {"Point", "MultiPoint"}
    islands = 0
    if weights == "knn" or points:
        w = libpysal.weights.KNN.from_dataframe(gdf, k=int(inputs.get("k", 8)))
        weights = "knn"
    else:
        w = libpysal.weights.Queen.from_dataframe(gdf, use_index=False, silence_warnings=True)
        islands = len(w.islands)
        if islands:  # islands get their nearest neighbour, so every feature has at least one
            w = libpysal.weights.attach_islands(w, libpysal.weights.KNN.from_dataframe(gdf, k=1))
    ctx.progress(0.4, "computing Gi*")
    g = G_Local(y, w, transform="B", star=True, permutations=999, seed=12345)
    z, p = np.asarray(g.Zs, dtype=float), np.asarray(g.p_sim, dtype=float)
    gdf["label"] = gdf[label].astype(str) if label else gdf["id"].astype(str)
    gdf["value"], gdf["gi_z"], gdf["gi_p"] = y, np.round(z, 3), np.round(p, 4)
    gdf["cluster"] = [classify(zi, pi) for zi, pi in zip(z, p)]
    ctx.progress(0.8, "writing")
    rows = ctx.write_layer(gdf, {"label": "text", "value": "double precision", "gi_z": "double precision",
                                 "gi_p": "double precision", "cluster": "text"})
    counts = gdf["cluster"].value_counts().to_dict()
    present = [(c, col) for c, col in CLASSES if c in counts]
    match = ["match", ["get", "cluster"]] + [x for c, col in present for x in (c, col)] + ["#f0f0f0"]
    style = ([{"type": "circle", "paint": {"circle-color": match, "circle-radius": 5, "circle-stroke-color": "#555555",
                                           "circle-stroke-width": 0.5}}] if points else
             [{"type": "fill", "paint": {"fill-color": match, "fill-opacity": 0.85}},
              {"type": "line", "paint": {"line-color": "#ffffff", "line-width": 0.4}}])
    return {
        "rows": rows,
        "title": f"Hot spots of {field}",
        "properties": ["label", "value", "gi_z", "gi_p", "cluster"],
        "style": {"kind": "maplibre", "layers": style},
        "legend": {"type": "categorical", "title": f"Gi* hot spots: {field}",
                   "items": [{"label": c, "color": col} for c, col in present]},
        "popup": "{label}: {value} ({cluster}, z {gi_z})",
        "report": {"features": total, "used": rows, "skipped_null": total - rows, "weights": weights,
                   "islands_given_nearest_neighbour": islands, "permutations": 999, "seed": 12345,
                   "clusters": {c: int(counts[c]) for c, _ in present},
                   "mean_value": {"hot_99": _mean(gdf, "Hot spot, 99 % confidence"),
                                  "cold_99": _mean(gdf, "Cold spot, 99 % confidence"), "all": float(np.mean(y))}},
    }


def _mean(gdf, cluster: str):
    sel = gdf.loc[gdf["cluster"] == cluster, "value"]
    return float(sel.mean()) if len(sel) else None
