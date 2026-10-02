#!/usr/bin/env python3
"""mapgen: create, validate and register map projects (plan Phase 3). Runs inside geotools.

Use the host wrapper `./mapgen`, which runs each step in the right container:

  ./mapgen new <slug> [--template vector-basic] [--title T] [--layer ID] [--from src_x.table]
  ./mapgen validate <slug> [--offline] [--json]    schema, rules, database, COGs (+ MapLibre style spec)
  ./mapgen apply <slug>        validate -> project SQL via the migrator -> tiPG refresh -> register
  ./mapgen sync [--check]      register every project in projects/index.json (--check: report drift only)
  ./mapgen export <slug>       write a project saved in the /new wizard to projects/<slug>/project.json
  ./mapgen list                projects in the registry
  ./mapgen import ...          alias for scripts/geoimport.py (recipes, one-off imports)

Files in projects/ are the source of truth in git; the registry (app.projects) is what core-api serves.
Validation lives in contracts/validate.py and is shared with core-api, so the CLI and the wizard agree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "contracts"))
sys.path.insert(0, str(REPO / "scripts"))

import validate as V  # noqa: E402  contracts/validate.py
from etl import health  # noqa: E402
from etl import outputs as outputs_mod  # noqa: E402

PROJECTS = REPO / "projects"
TEMPLATES = REPO / "templates" / "projects"
INDEX = PROJECTS / "index.json"
COG_DIR = REPO / "data" / "cog"
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
APP = "service=app"        # app_rw: registry writes
LOADER = "service=loader"  # dataset registry: which projects use which outputs
WHO = os.environ.get("TRIGGERED_BY", "cli:unknown")
# Errors that make a manifest unusable (sync skips it). Live errors (a missing view, ...) are registered
# with the report, so the hub still lists the project and the viewer shows which layer is broken.
STRUCTURAL = {"E_SCHEMA", "E_SOURCE_TYPE", "E_SLUG_MISMATCH", "E_DUP_LAYER", "E_READY_TODO", "E_NO_LAYERS",
              "E_ZOOM_RANGE", "E_CONTROL_PARAM"}


class MapgenError(Exception):
    pass


# ---- files ------------------------------------------------------------------------------------------

def read_index() -> list[str]:
    return json.loads(INDEX.read_text())["projects"]


def write_index(slugs: list[str]) -> None:
    INDEX.write_text(json.dumps({"projects": slugs}, indent=2) + "\n")


def manifest_path(slug: str) -> Path:
    return PROJECTS / slug / "project.json"


def load_manifest(slug: str) -> dict:
    if not SLUG.match(slug):
        raise MapgenError(f"invalid slug {slug!r}: lowercase letters, digits and single dashes")
    path = manifest_path(slug)
    if not path.exists():
        raise MapgenError(f"no {path.relative_to(REPO)} (create it with: ./mapgen new {slug})")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise MapgenError(f"{path.relative_to(REPO)} is not valid JSON: {e}") from None


def checksum(m: dict) -> str:
    return hashlib.sha256(V.normalize(m).encode()).hexdigest()


def cog_exists(name: str) -> bool:
    return (COG_DIR / f"{name}.tif").is_file()


# ---- validation ---------------------------------------------------------------------------------------

def run_validation(m: dict, slug: str, offline: bool) -> dict:
    if offline:
        return V.validate(m, slug)
    with psycopg.connect(APP) as conn:
        return V.validate(m, slug, conn=conn, cog_exists=cog_exists)


def print_report(slug: str, rep: dict) -> None:
    for level, items in (("ERROR", rep["errors"]), ("WARN", rep["warnings"])):
        for i in items:
            print(f"{level:<6}{i['code']:<20}{i['path']:<38}{i['message']}")
    state = "PASS" if rep["ok"] else "FAIL"
    print(f"{state}  {slug}: {len(rep['errors'])} error(s), {len(rep['warnings'])} warning(s) "
          f"[checked: {', '.join(rep['checked'])}]")


# ---- registry ------------------------------------------------------------------------------------------

def register(conn, m: dict, *, position: int, origin: str, rep: dict) -> str:
    """Upsert app.projects; a changed manifest becomes a new version. Returns created|updated|unchanged."""
    text, digest = V.normalize(m), checksum(m)
    row = conn.execute("SELECT checksum, version FROM app.projects WHERE slug = %s", (m["slug"],)).fetchone()
    if row and row[0] == digest:
        conn.execute("UPDATE app.projects SET position = %s, validation = %s WHERE slug = %s",
                     (position, json.dumps(rep), m["slug"]))
        return "unchanged"
    version = row[1] + 1 if row else 1
    conn.execute(
        """INSERT INTO app.projects (slug, title, status, position, manifest, checksum, version, origin, validation,
                                     updated_at, updated_by)
           VALUES (%(slug)s, %(title)s, %(status)s, %(pos)s, %(m)s::json, %(sum)s, %(v)s, %(origin)s, %(rep)s, now(), %(who)s)
           ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title, status = EXCLUDED.status,
               position = EXCLUDED.position, manifest = EXCLUDED.manifest, checksum = EXCLUDED.checksum,
               version = EXCLUDED.version, origin = EXCLUDED.origin, validation = EXCLUDED.validation,
               updated_at = now(), updated_by = EXCLUDED.updated_by""",
        {"slug": m["slug"], "title": m["title"], "status": m["status"], "pos": position, "m": text, "sum": digest,
         "v": version, "origin": origin, "rep": json.dumps(rep), "who": WHO})
    conn.execute("INSERT INTO app.manifest_versions (slug, version, manifest, checksum, origin, created_by) "
                 "VALUES (%s, %s, %s::json, %s, %s, %s)", (m["slug"], version, text, digest, origin, WHO))
    return "updated" if row else "created"


def refresh_usage(manifests: list[dict]) -> None:
    """Dashboard: re-discover the outputs of the recipes behind these projects' layers ('used by'), and
    health-check them (a new project's pub view and tiPG collection appear as outputs of its recipes)."""
    names = sorted({(l.get("source") or {}).get("collection") or (l.get("source") or {}).get("cog")
                    for m in manifests for l in m.get("layers", []) if l.get("status") != "todo"} - {None})
    if not names:
        return
    with psycopg.connect(LOADER) as conn:
        for recipe in outputs_mod.recipes_behind(conn, names):
            outputs_mod.refresh_outputs(conn, recipe, PROJECTS)
            health.check_outputs(conn, recipe)
        conn.commit()


# ---- commands --------------------------------------------------------------------------------------------

def render_template(a) -> tuple[dict, dict[str, str]]:
    """(manifest, {sql file name: text}) for `mapgen new` arguments, without writing anything."""
    slug = a.slug
    tdir = TEMPLATES / a.template
    if not (tdir / "project.json").is_file():
        raise MapgenError(f"no template {a.template!r}; available: "
                          f"{sorted(p.name for p in TEMPLATES.iterdir() if (p / 'project.json').is_file())}")
    if not SLUG.match(a.layer):
        raise MapgenError(f"invalid layer id {a.layer!r}")
    if a.source_table and not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", a.source_table):
        raise MapgenError(f"--from must be schema.table, got {a.source_table!r}")
    subs = {
        "{{slug}}": slug, "{{slug_}}": slug.replace("-", "_"), "{{title}}": a.title or slug.replace("-", " ").title(),
        "{{layer}}": a.layer, "{{layer_}}": a.layer.replace("-", "_"),
        "{{layer_title}}": a.layer_title or a.layer.replace("-", " ").capitalize(),
        "{{from}}": a.source_table or "src_schema.table_name",
    }

    def fill(text: str) -> str:
        for k, v in subs.items():
            text = text.replace(k, v)
        return text

    manifest = json.loads(fill((tdir / "project.json").read_text()))
    rep = V.validate(manifest, slug)
    if rep["errors"]:
        print_report(slug, rep)
        raise MapgenError("the template produced an invalid manifest (check the --title / --layer values)")
    sql = {fill(t.name.removesuffix(".tmpl")): fill(t.read_text()) for t in sorted((tdir / "sql").glob("*.sql.tmpl"))}
    return manifest, sql


def cmd_new(a) -> None:
    slug = a.slug
    if not SLUG.match(slug):
        raise MapgenError(f"invalid slug {slug!r}: lowercase letters, digits and single dashes")
    manifest, sql_files = render_template(a)
    if a.stdout:
        sys.stdout.write(V.normalize(manifest))
        return
    if (PROJECTS / slug).exists():
        raise MapgenError(f"projects/{slug}/ already exists")
    out = PROJECTS / slug
    out.mkdir(parents=True)
    manifest_path(slug).write_text(V.normalize(manifest))
    written = [manifest_path(slug)]
    for name, text in sql_files.items():
        (out / "sql").mkdir(exist_ok=True)
        (out / "sql" / name).write_text(text)
        written.append(out / "sql" / name)
    slugs = read_index()
    if slug not in slugs:
        write_index(slugs + [slug])
    for w in written:
        print(f"wrote {w.relative_to(REPO)}")
    print(f"added {slug} to projects/index.json")
    sql = [w for w in written if w.suffix == ".sql"]
    target = sql[0] if sql else manifest_path(slug)
    print(f"\nnext: edit {target.relative_to(REPO)}, then ./mapgen apply {slug}")


# Placeholder projects that must be reproducible from their templates (plan Phase 3, deliverable 6).
TEMPLATE_PROJECTS = [("hydrology-sketch", "hydro", "Hydrology Sketch"), ("analysis-sandbox", "analysis", "Analysis Sandbox")]


def cmd_check_templates(_a) -> None:
    failed = 0
    for slug, template, title in TEMPLATE_PROJECTS:
        args = argparse.Namespace(slug=slug, template=template, title=title, layer="features", layer_title=None,
                                  source_table=None)
        generated, _ = render_template(args)
        same = V.normalize(generated) == V.normalize(load_manifest(slug))
        failed += not same
        print(f"{'PASS' if same else 'FAIL'}  ./mapgen new {slug} --template {template} "
              f"{'reproduces' if same else 'differs from'} projects/{slug}/project.json")
    sys.exit(1 if failed else 0)


def cmd_validate(a) -> None:
    m = load_manifest(a.slug)
    rep = run_validation(m, a.slug, a.offline)
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(a.slug, rep)
    if not rep["ok"]:
        sys.exit(1)


def cmd_register(a) -> None:
    m = load_manifest(a.slug)
    rep = run_validation(m, a.slug, offline=False)
    print_report(a.slug, rep)
    if not rep["ok"]:
        raise MapgenError(f"{a.slug} was not registered: fix the errors above")
    slugs = read_index()
    position = slugs.index(a.slug) if a.slug in slugs else len(slugs)
    with psycopg.connect(APP) as conn:
        row = conn.execute("SELECT origin, checksum FROM app.projects WHERE slug = %s", (a.slug,)).fetchone()
        if row and row[0] == "api" and row[1] != checksum(m) and not a.force:
            raise MapgenError(f"{a.slug} was changed in the /new wizard after the file was written; "
                              f"run ./mapgen export {a.slug} first (or register --force to overwrite it)")
        result = register(conn, m, position=position, origin="file", rep=rep)
    refresh_usage([m])
    print(f"registered {a.slug} ({result})")


def cmd_sync(a) -> None:
    slugs = read_index()
    failed = drift = 0
    synced: list[dict] = []
    with psycopg.connect(APP) as conn:
        db = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT slug, checksum, origin FROM app.projects").fetchall()}
        for pos, slug in enumerate(slugs):
            try:
                m = load_manifest(slug)
            except MapgenError as e:
                print(f"FAIL  {e}")
                failed += 1
                continue
            digest, current = checksum(m), db.get(slug)
            if a.check:
                if current is None:
                    print(f"DRIFT {slug}: not registered (run ./mapgen sync)")
                    drift += 1
                elif current[0] != digest:
                    fix = f"./mapgen export {slug}" if current[1] == "api" else "./mapgen sync"
                    print(f"DRIFT {slug}: the registry differs from the file ({fix})")
                    drift += 1
                continue
            if current and current[1] == "api" and current[0] != digest:
                print(f"SKIP  {slug}: changed in the /new wizard; ./mapgen export {slug} keeps it (register --force drops it)")
                failed += 1
                continue
            rep = V.validate(m, slug, conn=conn, cog_exists=cog_exists)
            if any(e["code"] in STRUCTURAL for e in rep["errors"]):
                print_report(slug, rep)
                failed += 1
                continue
            result = register(conn, m, position=pos, origin="file", rep=rep)
            synced.append(m)
            if rep["ok"]:
                print(f"OK    {slug:<24}{result}")
            else:
                failed += 1
                print(f"WARN  {slug:<24}{result}; {len(rep['errors'])} live error(s): ./mapgen validate {slug}")
        for slug in sorted(set(db) - set(slugs)):
            print(f"INFO  {slug}: in the registry only (saved in the wizard; ./mapgen export {slug} writes the file)")
    if a.check:
        print(f"{'FAIL' if drift else 'PASS'}  projects/ and the registry {'differ' if drift else 'agree'} "
              f"({len(slugs)} files, {len(db)} registered)")
        sys.exit(1 if drift else 0)
    refresh_usage(synced)
    sys.exit(1 if failed else 0)


def cmd_export(a) -> None:
    with psycopg.connect(APP) as conn:
        row = conn.execute("SELECT manifest::text, checksum FROM app.projects WHERE slug = %s", (a.slug,)).fetchone()
        if not row:
            raise MapgenError(f"{a.slug} is not in the registry")
        m = json.loads(row[0])
        if a.stdout:
            sys.stdout.write(V.normalize(m))
            return
        path = manifest_path(a.slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(V.normalize(m))
        slugs = read_index()
        if a.slug not in slugs:
            write_index(slugs + [a.slug])
        conn.execute("UPDATE app.projects SET origin = 'file' WHERE slug = %s", (a.slug,))
    same = checksum(m) == row[1]
    print(f"wrote {path.relative_to(REPO)} ({'byte-identical to the registry' if same else 'normalized'})")


def cmd_list(_a) -> None:
    with psycopg.connect(APP) as conn:
        rows = conn.execute("SELECT slug, status, version, origin, updated_at::timestamp(0), updated_by, "
                            "coalesce((validation->>'ok')::boolean, false) FROM app.projects ORDER BY position, slug").fetchall()
    print(f"{'slug':<24}{'status':<8}{'ver':>4}  {'origin':<7}{'valid':<7}{'updated':<21}by")
    for slug, status, ver, origin, at, by, ok in rows:
        print(f"{slug:<24}{status:<8}{ver:>4}  {origin:<7}{'yes' if ok else 'NO':<7}{str(at):<21}{by}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="mapgen", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new", help="scaffold projects/<slug>/ from a template")
    p.add_argument("slug")
    p.add_argument("--template", default="vector-basic")
    p.add_argument("--title")
    p.add_argument("--layer", default="features", help="id of the first layer (vector-basic)")
    p.add_argument("--layer-title")
    p.add_argument("--from", dest="source_table", help="source table for the layer's view, e.g. src_census.cousub")
    p.add_argument("--stdout", action="store_true", help="print the manifest instead of writing files")
    p.set_defaults(func=cmd_new)
    sub.add_parser("check-templates", help="the placeholder projects must be reproducible from their templates"
                   ).set_defaults(func=cmd_check_templates)
    p = sub.add_parser("validate", help="validate a project (schema, rules, database, COGs)")
    p.add_argument("slug")
    p.add_argument("--offline", action="store_true", help="schema and rules only (no database)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("register", help="validate and register one project (used by apply)")
    p.add_argument("slug")
    p.add_argument("--force", action="store_true", help="overwrite a version saved in the wizard")
    p.set_defaults(func=cmd_register)
    p = sub.add_parser("sync", help="register every project in projects/index.json")
    p.add_argument("--check", action="store_true", help="only report drift between files and the registry")
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser("export", help="write a registry (wizard) project to projects/<slug>/project.json")
    p.add_argument("slug")
    p.add_argument("--stdout", action="store_true", help="print the normalized manifest instead of writing files")
    p.set_defaults(func=cmd_export)
    sub.add_parser("list", help="list registered projects").set_defaults(func=cmd_list)
    a = ap.parse_args()
    try:
        a.func(a)
    except MapgenError as e:
        print(f"mapgen: {e}", file=sys.stderr)
        sys.exit(1)
    except psycopg.OperationalError as e:
        print(f"mapgen: cannot reach the database ({str(e).strip().splitlines()[0]}); is the stack up (make up)?",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
