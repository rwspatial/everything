-- migrate:up
-- Extensions and the fixed (non-source) schemas.
-- Source schemas (src_*) are created in the roles migration via app.ensure_src_schema().

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS app;
COMMENT ON SCHEMA app IS 'Application state: project registry, dataset provenance, jobs. Never served by tiPG.';

CREATE SCHEMA IF NOT EXISTS pub;
COMMENT ON SCHEMA pub IS 'Publication surface: views and SQL functions only. The ONLY schema tiPG can see. Naming: pub.<project_slug>__<layer_id>.';

CREATE SCHEMA IF NOT EXISTS ml_out;
COMMENT ON SCHEMA ml_out IS 'Outputs written by R/Python workers (Phase 5). Never served directly.';

-- migrate:down
DROP SCHEMA IF EXISTS ml_out CASCADE;
DROP SCHEMA IF EXISTS pub CASCADE;
DROP SCHEMA IF EXISTS app CASCADE;
