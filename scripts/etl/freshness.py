"""Is what we loaded still what upstream offers? (plan §4, freshness methods)

Phase A implements `http_head` (single-file downloads such as Natural Earth): the ETag / Last-Modified /
Content-Length observed now is compared with the markers saved when the file was downloaded
(`<file>.headers.json` next to the cached download). Other methods report 'unknown' until their phase.
Single-file datasets keep their markers in app.dataset_parts under part_key '*'.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "spatial-geoimport/1"


PORTAL_ITEM = re.compile(r"^https://[^/]+/sharing/rest/content/items/([0-9a-f]{32})/data$")


def portal_item_markers(url: str) -> dict | None:
    """ArcGIS Online item downloads send no ETag/Last-Modified; use the item's own 'modified' time and size."""
    m = PORTAL_ITEM.match(url)
    if not m:
        return None
    meta_url = url.rsplit("/data", 1)[0] + "?f=json"
    with urllib.request.urlopen(urllib.request.Request(meta_url, headers={"User-Agent": USER_AGENT}), timeout=30) as r:
        meta = json.load(r)
    return {"etag": f"item-modified:{meta.get('modified')}", "last_modified": None, "bytes": meta.get("size") or None}


def head(url: str) -> dict:
    portal = portal_item_markers(url)
    if portal:
        return portal
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        h = r.headers
        return {"etag": h.get("ETag"), "last_modified": h.get("Last-Modified"),
                "bytes": int(h["Content-Length"]) if h.get("Content-Length") else None}


def marker(h: dict) -> str | None:
    """The value that identifies an upstream version: ETag if given, else Last-Modified + size."""
    if h.get("etag"):
        return h["etag"]
    if h.get("last_modified"):
        return f"{h['last_modified']}|{h.get('bytes')}"
    return None


def headers_sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".headers.json")


def record_loaded_part(conn, recipe: str, path: Path, run_id: int | None, checksum: str | None,
                       rows: int | None) -> None:
    """After a successful import: remember which upstream version we now hold."""
    side = headers_sidecar(path)
    h = json.loads(side.read_text()) if side.exists() else {}
    conn.execute(
        """INSERT INTO app.dataset_parts (recipe_name, part_key, part_kind, upstream_etag, upstream_last_modified,
                                          upstream_bytes, loaded_version, loaded_date, loaded_run_id, checksum,
                                          bytes, row_count, status, checked_at)
           VALUES (%s, '*', 'file', %s, %s, %s, %s, now(), %s, %s, %s, %s, %s, now())
           ON CONFLICT (recipe_name, part_key) DO UPDATE SET
               loaded_version = EXCLUDED.loaded_version, loaded_date = now(), loaded_run_id = EXCLUDED.loaded_run_id,
               checksum = EXCLUDED.checksum, bytes = EXCLUDED.bytes, row_count = EXCLUDED.row_count,
               upstream_etag = COALESCE(EXCLUDED.upstream_etag, app.dataset_parts.upstream_etag),
               upstream_last_modified = COALESCE(EXCLUDED.upstream_last_modified, app.dataset_parts.upstream_last_modified),
               upstream_bytes = COALESCE(EXCLUDED.upstream_bytes, app.dataset_parts.upstream_bytes),
               status = EXCLUDED.status, checked_at = now()""",
        (recipe, h.get("etag"), h.get("last_modified"), h.get("bytes"), marker(h), run_id, checksum,
         path.stat().st_size if path.exists() else None, rows, "current" if marker(h) else "unknown"),
    )


SDA = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
SSURGO_AREAS = re.compile(r"[A-Z]{2}[0-9]{0,3}%?")


def ssurgo_versions(areas: str) -> dict[str, str]:
    """{areasymbol: save date (YYYY-MM-DD)} for the SSURGO survey areas matching e.g. 'ME%', from SDA's sacatalog."""
    import datetime
    if not SSURGO_AREAS.fullmatch(areas):
        raise ValueError(f"bad survey area pattern {areas!r}")
    q = f"SELECT areasymbol, saverest FROM sacatalog WHERE areasymbol LIKE '{areas}' ORDER BY areasymbol"
    req = urllib.request.Request(SDA, data=json.dumps({"query": q, "format": "JSON"}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        rows = json.load(r).get("Table") or []
    return {a: datetime.datetime.strptime(d, "%m/%d/%Y %I:%M:%S %p").date().isoformat() for a, d in rows}


def record_survey_areas(conn, recipe: str, versions: dict[str, str], counts: dict[str, int], run_id: int | None) -> None:
    """After a SSURGO import: one dataset part per survey area, holding the save date we loaded."""
    conn.execute("DELETE FROM app.dataset_parts WHERE recipe_name = %s AND part_key <> ALL(%s)", (recipe, list(versions)))
    for area, version in versions.items():
        conn.execute(
            """INSERT INTO app.dataset_parts (recipe_name, part_key, part_kind, upstream_version, loaded_version,
                                              loaded_date, loaded_run_id, row_count, status, status_detail, checked_at)
               VALUES (%s, %s, 'survey_area', %s, %s, now(), %s, %s, %s, %s, now())
               ON CONFLICT (recipe_name, part_key) DO UPDATE SET part_kind = EXCLUDED.part_kind,
                   upstream_version = EXCLUDED.upstream_version, loaded_version = EXCLUDED.loaded_version,
                   loaded_date = now(), loaded_run_id = EXCLUDED.loaded_run_id, row_count = EXCLUDED.row_count,
                   status = EXCLUDED.status, status_detail = EXCLUDED.status_detail, checked_at = now()""",
            (recipe, area, version, version, run_id, counts.get(area),
             "current" if counts.get(area) else "missing", None if counts.get(area) else "no polygons loaded"))


def check_sda_sacatalog(conn, recipe: dict) -> tuple[str, dict, str]:
    """SSURGO: compare each survey area's save date in SDA with the one we loaded (one query for all areas)."""
    areas = (recipe.get("upstream") or {}).get("ssurgo_areas")
    if not areas:
        return "unknown", {}, "no upstream.ssurgo_areas pattern"
    try:
        now = ssurgo_versions(areas)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return "error", {}, f"Soil Data Access query failed: {e}"
    loaded = dict(conn.execute("SELECT part_key, loaded_version FROM app.dataset_parts WHERE recipe_name = %s",
                               (recipe["name"],)).fetchall())
    if not loaded:
        return "unknown", {"areas": len(now)}, "never downloaded"
    changed = sorted(a for a, v in now.items() if loaded.get(a) != v)
    for a, v in now.items():
        if a in loaded:
            conn.execute("UPDATE app.dataset_parts SET upstream_version = %s, status = %s, checked_at = now() "
                         "WHERE recipe_name = %s AND part_key = %s",
                         (v, "current" if loaded[a] == v else "stale", recipe["name"], a))
    observed = {"areas": len(now), "newest": max(now.values()) if now else None, "changed": changed}
    if changed:
        return "stale", observed, f"{len(changed)} survey area(s) re-published since our download: {', '.join(changed)}"
    return "current", observed, f"all {len(now)} survey areas unchanged since our download"


def arcgis_marker(url: str) -> dict:
    """Layer metadata of an ArcGIS Feature/Map Server layer: last data edit (ms since epoch) and name."""
    req = urllib.request.Request(f"{url.rstrip('/')}?f=json", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        meta = json.load(r)
    edit = (meta.get("editingInfo") or {}).get("dataLastEditDate") or (meta.get("editingInfo") or {}).get("lastEditDate")
    return {"last_edit": str(edit) if edit else None, "name": meta.get("name")}


def record_arcgis_part(conn, recipe: str, url: str, run_id: int | None, rows: int | None) -> None:
    try:
        marker_now = arcgis_marker(url).get("last_edit")
    except (urllib.error.URLError, TimeoutError, ValueError):
        marker_now = None
    conn.execute(
        """INSERT INTO app.dataset_parts (recipe_name, part_key, part_kind, upstream_version, loaded_version,
                                          loaded_date, loaded_run_id, row_count, status, checked_at)
           VALUES (%s, '*', 'service', %s, %s, now(), %s, %s, %s, now())
           ON CONFLICT (recipe_name, part_key) DO UPDATE SET upstream_version = EXCLUDED.upstream_version,
               loaded_version = EXCLUDED.loaded_version, loaded_date = now(), loaded_run_id = EXCLUDED.loaded_run_id,
               row_count = EXCLUDED.row_count, status = EXCLUDED.status, checked_at = now()""",
        (recipe, marker_now, marker_now, run_id, rows, "current" if marker_now else "unknown"),
    )


def check_arcgis_item(conn, recipe: dict) -> tuple[str, dict, str]:
    url = (recipe.get("upstream") or {}).get("arcgis")
    if not url:
        return "unknown", {}, "no ArcGIS service URL"
    try:
        now = arcgis_marker(url)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return "error", {}, f"service metadata request failed: {e}"
    part = conn.execute("SELECT loaded_version FROM app.dataset_parts WHERE recipe_name = %s AND part_key = '*'",
                        (recipe["name"],)).fetchone()
    loaded = part[0] if part else None
    if now.get("last_edit") is None:
        verdict, detail = "unknown", "service does not report a last-edit date"
    elif loaded is None:
        verdict, detail = "unknown", "never downloaded"
    else:
        verdict = "current" if loaded == now["last_edit"] else "stale"
        detail = "service unchanged since our download" if verdict == "current" else "service edited since our download"
    conn.execute(
        "UPDATE app.dataset_parts SET upstream_version = %s, status = %s, status_detail = %s, checked_at = now() "
        "WHERE recipe_name = %s AND part_key = '*'", (now.get("last_edit"), verdict, detail, recipe["name"]))
    return verdict, now, detail


def check_http_head(conn, recipe: dict, downloads: Path) -> tuple[str, dict, str]:
    url = (recipe.get("upstream") or {}).get("url")
    if not url:
        return "unknown", {}, "no upstream URL"
    try:
        now = head(url)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return "error", {}, f"HEAD failed: {e}"
    part = conn.execute(
        "SELECT loaded_version FROM app.dataset_parts WHERE recipe_name = %s AND part_key = '*'", (recipe["name"],)
    ).fetchone()
    loaded = part[0] if part else None
    detail = ""
    if loaded is None:
        # Baseline for files downloaded before markers were recorded: trust the cached file if its size matches.
        cached = downloads / ((recipe.get("upstream") or {}).get("filename") or url.rstrip("/").rsplit("/", 1)[-1])
        if cached.exists() and now.get("bytes") and cached.stat().st_size == now["bytes"]:
            loaded = marker(now)
            headers_sidecar(cached).write_text(json.dumps(now))
            detail = "baseline: cached download matches upstream size; markers recorded now"
    verdict = "unknown" if loaded is None or marker(now) is None else ("current" if loaded == marker(now) else "stale")
    if not detail:
        detail = {"current": "upstream unchanged since our download", "stale": "upstream changed since our download",
                  "unknown": "never downloaded" if loaded is None and not any(downloads.glob(
            (recipe.get("upstream") or {}).get("filename") or url.rstrip("/").rsplit("/", 1)[-1]))
                   else "no download markers yet (re-import once to record them)"}[verdict]
    conn.execute(
        """INSERT INTO app.dataset_parts (recipe_name, part_key, part_kind, upstream_etag, upstream_last_modified,
                                          upstream_bytes, loaded_version, status, status_detail, checked_at)
           VALUES (%s, '*', 'file', %s, %s, %s, %s, %s, %s, now())
           ON CONFLICT (recipe_name, part_key) DO UPDATE SET upstream_etag = EXCLUDED.upstream_etag,
               upstream_last_modified = EXCLUDED.upstream_last_modified, upstream_bytes = EXCLUDED.upstream_bytes,
               loaded_version = COALESCE(app.dataset_parts.loaded_version, EXCLUDED.loaded_version),
               status = EXCLUDED.status, status_detail = EXCLUDED.status_detail, checked_at = now()""",
        (recipe["name"], now.get("etag"), now.get("last_modified"), now.get("bytes"), loaded, verdict, detail),
    )
    return verdict, now, detail


def check(conn, recipe_name: str | None, downloads: Path) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        """SELECT name, upstream, freshness FROM app.recipes
           WHERE yaml_path IS NOT NULL AND (%s::text IS NULL OR name = %s) ORDER BY name""",
        (recipe_name, recipe_name),
    ).fetchall()
    out = []
    for name, upstream, fresh in rows:
        method = (fresh or {}).get("method", "none")
        if method == "arcgis_item":
            verdict, observed, detail = check_arcgis_item(conn, {"name": name, "upstream": upstream})
        elif method == "http_head":
            verdict, observed, detail = check_http_head(conn, {"name": name, "upstream": upstream}, downloads)
        elif method == "sda_sacatalog":
            verdict, observed, detail = check_sda_sacatalog(conn, {"name": name, "upstream": upstream})
        elif method == "none":
            verdict, observed, detail = "unknown", {}, "recipe declares no freshness method"
        else:
            verdict, observed, detail = "unknown", {}, f"method '{method}' arrives in a later phase"
        conn.execute(
            "INSERT INTO app.freshness_checks (recipe_name, part_key, method, observed, verdict, detail) VALUES (%s, '*', %s, %s, %s, %s)",
            (name, method, json.dumps(observed), verdict, detail),
        )
        out.append((name, verdict, detail))
    conn.commit()
    return out
