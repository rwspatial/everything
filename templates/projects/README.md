# Project templates (`./mapgen new <slug> --template <name>`)

Each template is a `project.json` plus optional `sql/*.sql.tmpl` files. `mapgen new` replaces the
placeholders, writes `projects/<slug>/`, and adds the slug to `projects/index.json`.

| Placeholder | Value |
|---|---|
| `{{slug}}` / `{{slug_}}` | project slug / with dashes as underscores (pub view names) |
| `{{title}}` | `--title`, default from the slug |
| `{{layer}}` / `{{layer_}}` / `{{layer_title}}` | `--layer` id (default `features`), underscored, `--layer-title` |
| `{{from}}` | `--from` source table for the first view (default `src_schema.table_name`) |

| Template | Status | What you get |
|---|---|---|
| `blank` | stub | no layers, a to-do note |
| `vector-basic` | draft | one `tipg-vector` layer on `pub.<slug_>__<layer_>` and the SQL for that view |
| `analysis` | stub | the analysis-sandbox layout: an empty landing project for Phase 5 job outputs |

`analysis` is the hand-built placeholder project turned into a template. `./mapgen check-templates`
(run by `make verify`) regenerates both placeholders from them and fails if the result differs from the files.

New projects default to a Maine view.
