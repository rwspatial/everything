"""Project manifest validation, shared by mapgen (geotools) and core-api (plan §3 Phase 3).

  validate_schema(m)       JSON Schema (contracts/project-manifest.v1.schema.json), with readable paths
  validate_rules(m, slug)  status-aware rules the schema can't express (duplicate ids, ready vs to-do, ...)
  validate_db(m, conn)     the live database: the pub view/function exists, reads only src_* / pub, tiPG can read it, one geometry
                           column with a declared SRID, an id column, a GiST index, and field names used by
                           properties / popups / styles exist. To-do layers are skipped.
  validate_cogs(m, fn)     raster-cog layers: titiler can open data/cog/<name>.tif

Every issue has a stable code (E_* errors block apply/save, W_* warnings don't). The MapLibre style
spec itself is checked by frontend/scripts/validate-styles.mjs (node), not here.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from jsonschema import Draft7Validator

SCHEMA_PATH = Path(__file__).with_name("project-manifest.v1.schema.json")
SCHEMA = json.loads(SCHEMA_PATH.read_text())
_VALIDATOR = Draft7Validator(SCHEMA)
SOURCE_TYPES = [SCHEMA["definitions"][d["$ref"].split("/")[-1]]["properties"]["type"]["const"]
                for d in SCHEMA["definitions"]["SourceSpec"]["oneOf"]]
TEMPLATE_FIELD = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class Issue:
    code: str
    path: str
    message: str

    @property
    def level(self) -> str:
        return "error" if self.code.startswith("E_") else "warning"

    def as_dict(self) -> dict:
        return {**asdict(self), "level": self.level}


def _path(parts: Iterable[Any]) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "(manifest)"


def _branch_errors(err):
    """For a oneOf failure on a {type: ...} union, the errors of the branch whose `type` matched (or None)."""
    by_branch: dict[int, list] = {}
    for e in err.context:
        by_branch.setdefault(e.relative_schema_path[0], []).append(e)
    for branch in by_branch.values():
        if not any(list(e.relative_path)[:1] == ["type"] or (not e.relative_path and e.validator == "required"
                   and "'type'" in e.message) for e in branch):
            return branch
    return None


def validate_schema(m: Any) -> list[Issue]:
    issues: list[Issue] = []
    for err in sorted(_VALIDATOR.iter_errors(m), key=lambda e: list(map(str, e.absolute_path))):
        path = list(err.absolute_path)
        if err.validator == "oneOf" and isinstance(err.instance, dict):
            branch = _branch_errors(err)
            if branch is None:
                if path[-1:] == ["source"]:
                    issues.append(Issue("E_SOURCE_TYPE", _path(path + ["type"]),
                                        f"unknown source type {err.instance.get('type')!r} (known: {', '.join(SOURCE_TYPES)})"))
                else:
                    issues.append(Issue("E_SCHEMA", _path(path + ["type"]), f"unknown type {err.instance.get('type')!r}"))
                continue
            for e in branch:
                issues.append(Issue("E_SCHEMA", _path(path + list(e.relative_path)), e.message))
            continue
        issues.append(Issue("E_SCHEMA", _path(path), err.message))
    return issues


def _style_fields(node: Any) -> set[str]:
    """Property names read by MapLibre expressions: ["get", "name"] and ["has", "name"]."""
    found: set[str] = set()
    if isinstance(node, list):
        if len(node) == 2 and node[0] in ("get", "has") and isinstance(node[1], str):
            found.add(node[1])
        for x in node:
            found |= _style_fields(x)
    elif isinstance(node, dict):
        for x in node.values():
            found |= _style_fields(x)
    return found


def validate_rules(m: dict, slug: str | None = None) -> list[Issue]:
    issues: list[Issue] = []
    if slug is not None and m.get("slug") != slug:
        issues.append(Issue("E_SLUG_MISMATCH", "slug", f"manifest slug {m.get('slug')!r} does not match its folder/URL {slug!r}"))
    layers = m.get("layers") or []
    seen: set[str] = set()
    for i, layer in enumerate(layers):
        lid = layer.get("id")
        if lid in seen:
            issues.append(Issue("E_DUP_LAYER", f"layers[{i}].id", f"layer id {lid!r} is used twice"))
        seen.add(lid)
        todo = layer.get("status") == "todo"
        if todo and not layer.get("todo"):
            issues.append(Issue("W_TODO_REASON", f"layers[{i}].todo", "to-do layer has no `todo` text saying what is missing"))
        if m.get("status") == "ready" and todo:
            issues.append(Issue("E_READY_TODO", f"layers[{i}].status", "a ready project cannot contain to-do layers"))
        lo, hi = layer.get("minzoom"), layer.get("maxzoom")
        if lo is not None and hi is not None and lo > hi:
            issues.append(Issue("E_ZOOM_RANGE", f"layers[{i}]", f"minzoom {lo} is above maxzoom {hi}"))
        params = (layer.get("source") or {}).get("params") or {}
        for j, c in enumerate(layer.get("controls") or []):
            if c.get("param") not in params:
                issues.append(Issue("E_CONTROL_PARAM", f"layers[{i}].controls[{j}].param",
                                    f"control {c.get('param')!r} has no default in source.params"))
            elif not (c["min"] <= float(params[c["param"]]) <= c["max"]):
                issues.append(Issue("W_CONTROL_RANGE", f"layers[{i}].controls[{j}]",
                                    f"default {params[c['param']]} is outside {c['min']}..{c['max']}"))
        if not todo and not layer.get("style") and (layer.get("source") or {}).get("type") not in ("raster-xyz", "raster-cog"):
            issues.append(Issue("W_NO_STYLE", f"layers[{i}].style", "vector layer has no style; it draws with defaults"))
    if m.get("status") in ("draft", "ready") and not any(l.get("status") != "todo" for l in layers):
        issues.append(Issue("E_NO_LAYERS", "layers", f"a {m.get('status')} project needs at least one layer that is not a to-do"))
    return issues


# ---- database ------------------------------------------------------------------------------------

_REL_SQL = """
SELECT c.oid, c.relkind,
       has_table_privilege('tipg_ro', c.oid, 'SELECT') AS served,
       coalesce((SELECT json_agg(json_build_object('name', a.attname, 'srid', postgis_typmod_srid(a.atttypmod),
                                                   'type', postgis_typmod_type(a.atttypmod)))
                 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.atttypid = 'geometry'::regtype
                   AND a.attnum > 0 AND NOT a.attisdropped), '[]') AS geoms,
       (SELECT array_agg(a.attname::text) FROM pg_attribute a
         WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) AS columns,
       (SELECT array_agg(a.attname::text) FROM pg_attribute a
         WHERE a.attrelid = c.oid AND a.atttypid = 'numeric'::regtype AND a.attnum > 0 AND NOT a.attisdropped) AS numeric_columns,
       CASE WHEN c.relkind = 'v' THEN
         (SELECT coalesce(bool_or(EXISTS (
                   SELECT 1 FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_am am ON am.oid = ic.relam
                   WHERE i.indrelid = d.refobjid AND am.amname = 'gist')), false)
            FROM pg_rewrite r JOIN pg_depend d ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass
                              AND d.refclassid = 'pg_class'::regclass
            WHERE r.ev_class = c.oid AND d.refobjid <> c.oid)
       ELSE EXISTS (SELECT 1 FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_am am ON am.oid = ic.relam
                    WHERE i.indrelid = c.oid AND am.amname = 'gist') END AS gist,
       (SELECT coalesce(sum(greatest(t.reltuples, 0)), 0)::bigint FROM pg_rewrite r
          JOIN pg_depend d ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass AND d.refclassid = 'pg_class'::regclass
          JOIN pg_class t ON t.oid = d.refobjid AND t.relkind = 'r'
          WHERE r.ev_class = c.oid) AS est_rows,
       (SELECT array_agg(DISTINCT t.relnamespace::regnamespace::text || '.' || t.relname) FROM pg_rewrite r
          JOIN pg_depend d ON d.objid = r.oid AND d.classid = 'pg_rewrite'::regclass AND d.refclassid = 'pg_class'::regclass
          JOIN pg_class t ON t.oid = d.refobjid
          WHERE r.ev_class = c.oid AND d.refobjid <> c.oid
            AND NOT (t.relnamespace::regnamespace::text IN ('pub', 'ml_out')
                     OR t.relnamespace::regnamespace::text LIKE 'src\\_%%')
       ) AS foreign_sources
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'pub' AND c.relname = %s AND c.relkind IN ('v', 'm', 'r')
"""

_FN_SQL = """
SELECT p.proargnames::text[] AS argnames, p.proargmodes::text[] AS argmodes,
       coalesce(p.proallargtypes, p.proargtypes::oid[])::oid[] AS argtypes,
       has_function_privilege('tipg_ro', p.oid, 'EXECUTE') AS served
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'pub' AND p.proname = %s
"""


def _row(conn, sql: str, *args) -> dict | None:
    cur = conn.execute(sql, args)
    row = cur.fetchone()
    if row is None:
        return None
    return row if isinstance(row, dict) else dict(zip([d.name for d in cur.description], row))


def _check_fields(i: int, layer: dict, coll: str, columns: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    src = layer["source"]
    for p in src.get("properties") or []:
        if p not in columns:
            issues.append(Issue("E_PROPERTY_UNKNOWN", f"layers[{i}].source.properties", f"{coll} has no column {p!r}"))
    template = ((layer.get("interaction") or {}).get("popup") or {}).get("template", "")
    in_template = set(TEMPLATE_FIELD.findall(template))
    in_style = _style_fields((layer.get("style") or {}).get("layers"))
    for f in sorted(in_template - columns):
        issues.append(Issue("W_TEMPLATE_FIELD", f"layers[{i}].interaction.popup.template", f"{coll} has no column {f!r}"))
    for f in sorted(in_style - columns):
        issues.append(Issue("W_STYLE_FIELD", f"layers[{i}].style", f"the style reads {f!r}, which {coll} does not have"))
    if src.get("type") == "tipg-vector" and src.get("properties") is not None:
        missing = sorted(((in_template | in_style) & columns) - set(src["properties"]))
        if missing:
            issues.append(Issue("W_PROPERTY_FILTERED", f"layers[{i}].source.properties",
                                f"{', '.join(missing)} used by the popup/style but not listed in properties, so tiles omit it"))
    return issues


def validate_db(m: dict, conn) -> list[Issue]:
    issues: list[Issue] = []
    geometry_oid = _row(conn, "SELECT 'geometry'::regtype::oid AS oid")["oid"]
    for i, layer in enumerate(m.get("layers") or []):
        src = layer.get("source") or {}
        coll = src.get("collection")
        if layer.get("status") == "todo" or not coll:
            continue
        at = f"layers[{i}].source.collection"
        name = coll.split(".", 1)[1]
        rel = _row(conn, _REL_SQL, name)
        if rel:
            columns = set(rel["columns"] or [])
            geoms = rel["geoms"] if isinstance(rel["geoms"], list) else json.loads(rel["geoms"])
            if rel["foreign_sources"]:
                issues.append(Issue("E_VIEW_SOURCE", at, f"{coll} reads {', '.join(sorted(rel['foreign_sources']))}; "
                                    "published views may only read src_* tables, analysis outputs (ml_out) and other pub views"))
            if not rel["served"]:
                issues.append(Issue("E_NOT_SERVED", at, f"{coll} exists but tipg_ro cannot read it; create pub objects "
                                    "through the migrator (mapgen apply / make seed) so the default grants apply"))
            if not geoms:
                issues.append(Issue("E_NO_GEOM", at, f"{coll} has no geometry column"))
            elif len(geoms) > 1:
                issues.append(Issue("E_MULTI_GEOM", at, f"{coll} has {len(geoms)} geometry columns; publish exactly one"))
            elif not geoms[0]["srid"]:
                issues.append(Issue("E_SRID", at, f"{coll}.{geoms[0]['name']} has no declared SRID; cast it in the view, "
                                    "e.g. geom::geometry(MultiPolygon, 4326)"))
            if "id" not in columns:
                issues.append(Issue("E_NO_ID", at, f"{coll} has no `id` column (tiPG uses it as the feature id)"))
            if geoms and not rel["gist"]:
                issues.append(Issue("W_NO_GIST", at, f"no GiST index on the table behind {coll}; tiles will be slow"))
            if src.get("type") == "tipg-geojson" and rel["est_rows"] > (src.get("limit") or 5000):
                issues.append(Issue("W_GEOJSON_ROWS", at, f"about {rel['est_rows']:,} rows behind {coll}; GeoJSON loads "
                                    "them all at once, use tipg-vector (tiles) instead"))
        else:
            fn = _row(conn, _FN_SQL, name)
            if not fn:
                issues.append(Issue("E_VIEW_MISSING", at, f"{coll} does not exist in pub (run the project's SQL with "
                                    "mapgen apply, or make seed, then make refresh)"))
                continue
            if not fn["served"]:
                issues.append(Issue("E_NOT_SERVED", at, f"tipg_ro cannot execute {coll}"))
            names = fn["argnames"] or []
            modes = fn["argmodes"] or ["i"] * len(names)
            outs = [(n, t) for n, md, t in zip(names, modes, fn["argtypes"]) if md in ("o", "t", "b")]
            ins = {n for n, md in zip(names, modes) if md in ("i", "b")}
            columns = {n for n, _ in outs}
            if not any(t == geometry_oid for _, t in outs):
                issues.append(Issue("E_NO_GEOM", at, f"{coll} returns no geometry column"))
            if "id" not in columns:
                issues.append(Issue("E_NO_ID", at, f"{coll} returns no `id` column"))
            for p in (src.get("params") or {}):
                if p not in ins:
                    issues.append(Issue("E_PARAM_UNKNOWN", f"layers[{i}].source.params.{p}",
                                        f"{coll} has no argument {p!r} (arguments: {', '.join(sorted(ins)) or 'none'})"))
        issues += _check_fields(i, layer, coll, columns)
        if rel:
            for f in sorted(_style_fields((layer.get("style") or {}).get("layers")) & set(rel["numeric_columns"] or [])):
                issues.append(Issue("W_STYLE_NUMERIC", f"layers[{i}].style",
                                    f"the style reads {f!r}, a numeric column: tiPG sends numeric as text in vector tiles, so "
                                    f"number expressions fail; cast it in the view ({f}::float8)"))
    return issues


def validate_cogs(m: dict, cog_exists: Callable[[str], bool]) -> list[Issue]:
    issues = []
    for i, layer in enumerate(m.get("layers") or []):
        src = layer.get("source") or {}
        if layer.get("status") != "todo" and src.get("type") == "raster-cog" and not cog_exists(src["cog"]):
            issues.append(Issue("E_COG_MISSING", f"layers[{i}].source.cog",
                                f"data/cog/{src['cog']}.tif is missing or titiler cannot open it"))
    return issues


def report(issues: list[Issue], checked: list[str]) -> dict:
    errors = [i.as_dict() for i in issues if i.level == "error"]
    warnings = [i.as_dict() for i in issues if i.level == "warning"]
    return {"ok": not errors, "errors": errors, "warnings": warnings, "checked": checked}


def validate(m: Any, slug: str | None = None, conn=None, cog_exists: Callable[[str], bool] | None = None) -> dict:
    """Run every check available here. Rules and live checks only run on a schema-valid manifest."""
    issues = validate_schema(m)
    checked = ["schema"]
    if not issues:
        issues += validate_rules(m, slug)
        checked.append("rules")
        if conn is not None:
            issues += validate_db(m, conn)
            checked.append("database")
        if cog_exists is not None:
            issues += validate_cogs(m, cog_exists)
            checked.append("cogs")
    return report(issues, checked)


def normalize(m: dict) -> str:
    """Canonical file form: 2-space JSON, key order as given, UTF-8 kept, trailing newline."""
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"
