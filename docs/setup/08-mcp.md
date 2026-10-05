# 08 · MCP servers (Phase 4)

MCP servers let Claude Code (or any MCP client) work with this stack through a small set of tools, each with
its own credential. They run in the `spatial/mcp` image (`mcp/`) and Claude Code starts them over stdio, one
container per session. They have no ports and join only internal networks (`spatial-db`: `data`; `project-pipeline`: `api`).

| Server | What it can do | Credential | Status |
|---|---|---|---|
| `spatial-db` | Explore and query the database, read-only | `mcp_ro`: `SELECT` on `pub` and `src_*`, nothing in `app` | built |
| `project-pipeline` | Validate manifests, propose views as SQL files, write manifests, hand back the publish command | `MCP_PIPELINE_TOKEN`: core-api project validation + field stats only | built |
| `analysis` | List R/Python processes, submit jobs, follow them, read results, cancel | `MCP_ANALYSIS_TOKEN`: core-api processes + jobs only | built |

## Set up (once)

```bash
make mcp-credentials   # adds MCP_DB_PASSWORD, MCP_PIPELINE_TOKEN and MCP_ANALYSIS_TOKEN to .env (if missing) and applies them
make mcp-build         # builds spatial/mcp
make mcp-test          # smoke test over stdio (also part of make verify)
```

`.mcp.json` in the repository root registers the three servers for Claude Code (`spatial-db` runs the `mcp-db`
service, `project-pipeline` runs `mcp-pipeline`, `analysis` runs `mcp-analysis`), each as
`docker compose run --rm -T --no-deps <service>`. The analysis server needs a running worker (`make workers-up`).

Start Claude Code in the repository folder, approve the project's servers when asked, and check them with `/mcp`.
The stack must be up (`make up`): the servers use the running `postgis`, `core-api` and `tipg`.

## spatial-db tools

| Tool | Returns |
|---|---|
| `list_schemas()` | `pub` and the `src_*` schemas with table counts |
| `list_tables(schema)` | Tables, views and functions: kind, geometry type, SRID, estimated rows, comment |
| `describe_table(name)` | Columns, geometry, indexes; for a view, its SQL and the source tables it reads |
| `run_readonly_sql(sql_text, limit=200)` | One read statement, at most 1,000 rows, with a `truncated` flag |
| `spatial_summary(table, field?)` | Row count, geometry types, SRID, lon/lat extent, empty and invalid geometries; a field's distribution |

The resource `schema://<name>` (e.g. `schema://src_census`) lists a schema as Markdown.

Things to ask, for example:
- "Which Maine towns have the highest median household income, and what is the margin of error?"
- "How many E911 address points are in Cumberland County?"
- "Describe pub.maine_water__wetlands and summarise its wetland types."

## project-pipeline tools

| Tool | What it does |
|---|---|
| `list_projects()`, `get_manifest(slug)` | The registry, and a project's manifest (file first) with its SQL files |
| `validate_manifest(manifest)` | The same checks as `./mapgen validate` and the wizard (schema, rules, live database, COGs) |
| `collection_fields(collection)`, `layer_stats(collection, field, classes=5)` | Fields of a pub view; quantile breaks or top values for styling |
| `propose_view(slug, layer_id, select_sql)` | Writes `projects/<slug>/sql/NNN_<layer>.sql`: `CREATE OR REPLACE VIEW pub.<slug_>__<layer_> AS <your SELECT>` |
| `write_manifest(slug, manifest)` | Validates, then writes `projects/<slug>/project.json` and lists it in `projects/index.json` |
| `apply_project(slug)` | Checks the project and returns `./mapgen apply <slug>` and what it will run. It does not run it |
| `preview_urls(slug)` | Viewer link and a test tile per layer, with the status tiPG returns |

The flow, with the person in the loop where Docker is needed:

1. **Agent:** explores with `spatial-db`.
2. **Agent:** `propose_view` writes the SQL file.
3. **Agent:** `write_manifest` writes the manifest. The view doesn't exist yet, so its `E_VIEW_MISSING` is marked
   `pending_apply`.
4. **Agent:** `apply_project` returns the command.
5. **Person:** reviews the files (`git diff`) and approves `./mapgen apply <slug>` when Claude Code asks to run it.
6. **Agent:** `preview_urls` confirms the published layer.

`make mcp-test` runs this whole flow on Maine data (Washington and Hancock County towns), approves the command
itself, checks the published project, and removes everything it created.

## analysis tools

| Tool | What it does |
|---|---|
| `list_processes()`, `describe_process(id)` | Processes and their inputs (types, defaults, ranges), and whether a worker is online |
| `submit_job(process_id, inputs)` | Queues a job after core-api checks the inputs against the process and the database |
| `job_status(job_id)`, `job_result(job_id, wait_seconds)` | Progress; then the report and the LayerSpec of the output layer |
| `cancel_job(job_id)` | Stops a queued or running job; its output is discarded |

For example: "Run the vulnerability assessment for Castine and tell me which bridges are in the 1% flood zone." Results become
layers on `pub.analysis_sandbox__job_<id>`. A person adds them to a map in the project workspace, because the analysis
token cannot promote layers. See docs/setup/09-ml-workers.md.

## Safety

Each layer refuses writes on its own, so a single failure doesn't open the database:

1. **Server.** `run_readonly_sql` accepts one `SELECT`, `WITH`, `EXPLAIN`, `SHOW`, `VALUES` or `TABLE` statement.
   psycopg's extended protocol rejects a second statement. Results stream from a server-side cursor, which also
   refuses data-modifying `WITH`.
2. **Transaction.** Every transaction is `READ ONLY`, and statements are cancelled after 15 seconds.
3. **Role.** `mcp_ro` holds only `SELECT` (and `EXECUTE` on `pub` functions). It has no rights in `app` and cannot
   create objects anywhere. It is read-only and time-limited by default, with at most 5 connections.
4. **Container.** Read-only filesystem, all capabilities dropped, no new privileges, the internal `data` network
   only, and no Docker socket.

project-pipeline has no database credential and no Docker socket. It sits on the internal `api` network only, and
its one writable folder is `projects/`. Its token opens only project validation and field statistics in core-api;
saving, deleting, datasets and runs answer 401. Through the public proxy, `/api/admin/*` still needs the admin
login. Proposed SQL must be a single `SELECT` that reads `src_*` or `pub`. A published view that reads anything
else fails validation (`E_VIEW_SOURCE`), whoever wrote it. Nothing is published until a person runs
`./mapgen apply`.

`make mcp-test` checks every layer: it tries `INSERT`, DDL, two statements, a writable CTE, reading `app`,
switching to read-write and a 30-second query through the server, and `INSERT`, `UPDATE` and `CREATE` directly as
`mcp_ro`.

To withdraw access, empty `MCP_DB_PASSWORD` in `.env` and run `make migrate`. With an empty password the role
can no longer log in.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `password authentication failed for user "mcp_ro"` | `make mcp-credentials` |
| project-pipeline: `MCP_PIPELINE_TOKEN is not set` or HTTP 401 | `make mcp-credentials` (it also restarts core-api with the token) |
| `/mcp` shows the server as failed | `make up`, then `make mcp-test` to see the error outside Claude Code |
| `canceling statement due to statement timeout` | Add `WHERE` / `LIMIT`, or use `spatial_summary`; big tables are `src_nwi.wetlands` and `src_e911.addresses` |
