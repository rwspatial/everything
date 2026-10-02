# MCP servers (plan Phase 4)

Python package `spatial_mcp`, one module per server, built into the `spatial/mcp` image (`mcp/Dockerfile`).
Claude Code starts them over stdio through `.mcp.json`; see `docs/setup/08-mcp.md`.

| Server | Module | Credential | Status |
|---|---|---|---|
| spatial-db | `spatial_mcp.spatial_db` | `mcp_ro`: read-only, `pub` + `src_*` | built |
| project-pipeline | `spatial_mcp.project_pipeline` | `MCP_PIPELINE_TOKEN` (core-api validate + stats) | built |
| analysis | `spatial_mcp.analysis` | `MCP_ANALYSIS_TOKEN` (core-api processes + jobs) | built |

Tests over real stdio: `make mcp-test` (spatial-db smoke test, then `scripts/mcp_pipeline_e2e.sh`: propose ->
write -> apply -> published, on Maine data).
