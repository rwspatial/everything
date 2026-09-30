"""Mirror data/recipes/*.yaml into app.recipes, and report API-key status (never values).

YAML is the source of truth: every field here is overwritten on each sync. Recipes whose file
disappeared keep their row (history stays attached) with yaml_path = NULL ("orphaned").
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import yaml

# Keys a recipe may declare, and keys the dashboard knows about even before a recipe needs them.
KNOWN_KEYS = ["CENSUS_API_KEY", "EARTHDATA_TOKEN", "PC_SDK_SUBSCRIPTION_KEY"]


def _normalize(r: dict) -> dict:
    """Recipe v1 keys map onto v2 fields (plan §3): source.url -> upstream, target -> one postgis_table output."""
    src = r.get("source") or {}
    upstream = r.get("upstream") or {k: src[k] for k in ("url", "path", "filename") if src.get(k)}
    if src.get("arcgis"):
        upstream = {"arcgis": src["arcgis"]["url"], "where": src["arcgis"].get("where", "1=1")}
    kind = r.get("kind", "vector")
    outputs = r.get("outputs") or ([{"type": "postgis_table", "target": r["target"]}] if r.get("target") else [])
    freshness = r.get("freshness") or (
        {"method": "http_head", "every": "30d"} if src.get("url")
        else {"method": "arcgis_item", "every": "7d"} if src.get("arcgis") else {"method": "none"})
    return {
        "kind": kind,
        "group_name": r.get("group"),
        "title": r.get("title") or r.get("description") or r["name"],
        "description": r.get("description"),
        "agency": r.get("agency"),
        "upstream": upstream,
        "license": r.get("license"),
        "attribution": r.get("attribution"),
        "vintage": r.get("vintage") or {},
        "coverage": r.get("coverage") or {},
        "parts": r.get("parts") or {},
        "requires_keys": list(r.get("requires_keys") or []),
        "outputs": outputs,
        "steps": r.get("steps") or [],
        "freshness": freshness,
        "retention": r.get("retention") or {},
        "concurrency_class": r.get("concurrency", "network"),
        "enabled": r.get("enabled", True) is not False,
        "todo": r.get("todo"),
    }


def sync_recipes(conn, recipes_dir: Path) -> dict:
    """Upsert every YAML recipe; returns {'synced': n, 'errors': {...}, 'orphaned': [...]}"""
    seen, errors = [], {}
    for path in sorted(recipes_dir.glob("*.yaml")):
        text = path.read_text()
        digest = hashlib.sha256(text.encode()).hexdigest()
        name = path.stem
        try:
            r = yaml.safe_load(text) or {}
            if r.get("name") != name:
                raise ValueError(f"'name' must equal the file name ({name})")
            row = _normalize(r)
            err = None
        except Exception as e:  # noqa: BLE001 - a broken YAML must not block syncing the others
            row, err = None, str(e)
            errors[name] = err
        seen.append(name)
        if row is None:
            conn.execute(
                """INSERT INTO app.recipes (name, yaml_path, yaml_sha256, yaml_text, synced_at, sync_error)
                   VALUES (%s, %s, %s, %s, now(), %s)
                   ON CONFLICT (name) DO UPDATE SET yaml_path = EXCLUDED.yaml_path, yaml_sha256 = EXCLUDED.yaml_sha256,
                       yaml_text = EXCLUDED.yaml_text, synced_at = now(), sync_error = EXCLUDED.sync_error""",
                (name, f"data/recipes/{path.name}", digest, text, err),
            )
            continue
        cols = list(row)
        jsonb = {"upstream", "vintage", "coverage", "parts", "outputs", "steps", "freshness", "retention"}
        values = [json.dumps(row[c]) if c in jsonb else row[c] for c in cols]
        conn.execute(
            f"""INSERT INTO app.recipes (name, {", ".join(cols)}, yaml_path, yaml_sha256, yaml_text, synced_at, sync_error)
                VALUES (%s, {", ".join(["%s"] * len(cols))}, %s, %s, %s, now(), NULL)
                ON CONFLICT (name) DO UPDATE SET {", ".join(f"{c} = EXCLUDED.{c}" for c in cols)},
                    yaml_path = EXCLUDED.yaml_path, yaml_sha256 = EXCLUDED.yaml_sha256,
                    yaml_text = EXCLUDED.yaml_text, synced_at = now(), sync_error = NULL""",
            (name, *values, f"data/recipes/{path.name}", digest, text),
        )
    orphaned = [r[0] for r in conn.execute(
        "UPDATE app.recipes SET yaml_path = NULL, synced_at = now() WHERE NOT (name = ANY(%s)) AND yaml_path IS NOT NULL RETURNING name",
        (seen,),
    ).fetchall()]
    sync_secret_status(conn)
    conn.commit()
    return {"synced": len(seen), "errors": errors, "orphaned": orphaned}


def sync_secret_status(conn) -> None:
    """Record which keys are configured in *this* process (CLI geotools / worker). Values never leave it."""
    required: dict[str, list[str]] = {}
    for name, keys in conn.execute("SELECT name, requires_keys FROM app.recipes WHERE yaml_path IS NOT NULL"):
        for k in keys or []:
            required.setdefault(k, []).append(name)
    for key in sorted(set(KNOWN_KEYS) | set(required)):
        value = os.environ.get(key) or ""
        conn.execute(
            """INSERT INTO app.secrets_status (key_name, configured, fingerprint, required_by, reported_at)
               VALUES (%s, %s, %s, %s, now())
               ON CONFLICT (key_name) DO UPDATE SET configured = EXCLUDED.configured,
                   fingerprint = EXCLUDED.fingerprint, required_by = EXCLUDED.required_by, reported_at = now()""",
            (key, bool(value), hashlib.sha256(value.encode()).hexdigest()[:8] if value else None,
             sorted(required.get(key, []))),
        )


def missing_keys(recipe: dict) -> list[str]:
    """Keys a recipe declares but this process does not have (fail fast before any network call)."""
    return [k for k in recipe.get("requires_keys") or [] if not os.environ.get(k)]
