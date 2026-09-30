-- migrate:up
-- Dataset registry for the admin dashboard (plan: .claude/plans/admin-dashboard.plan.md §2).
-- YAML recipes stay the source of truth: app.recipes is a synced mirror (make recipes-sync).
-- Everything else records what actually happened: runs, jobs, outputs, coverage, parts,
-- freshness observations and key status. No secret values are ever stored here.
--
--   role        | used by                  | can
--   ------------+--------------------------+---------------------------------------------------
--   etl_runner  | (group) loader, worker   | read/write the registry tables below
--   admin_api   | core-api (/api/admin/*)  | read the registry. Nothing else

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admin_api') THEN
    CREATE ROLE admin_api LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_runner') THEN
    CREATE ROLE etl_runner NOLOGIN;
  END IF;
END $$;
GRANT etl_runner TO loader;
GRANT USAGE ON SCHEMA app TO admin_api;

-- Mirror of data/recipes/*.yaml (one row per recipe; rows are never deleted, orphans keep yaml_path NULL).
CREATE TABLE app.recipes (
  name              text PRIMARY KEY,
  kind              text NOT NULL DEFAULT 'vector' CHECK (kind IN ('vector', 'table', 'raster', 'multi')),
  group_name        text,
  title             text,
  description       text,
  agency            text,
  upstream          jsonb NOT NULL DEFAULT '{}',
  license           text,
  attribution       text,
  vintage           jsonb NOT NULL DEFAULT '{}',
  coverage          jsonb NOT NULL DEFAULT '{}',
  parts             jsonb NOT NULL DEFAULT '{}',
  requires_keys     text[] NOT NULL DEFAULT '{}',
  outputs           jsonb NOT NULL DEFAULT '[]',
  steps             jsonb NOT NULL DEFAULT '[]',
  freshness         jsonb NOT NULL DEFAULT '{}',
  retention         jsonb NOT NULL DEFAULT '{}',
  concurrency_class text NOT NULL DEFAULT 'network' CHECK (concurrency_class IN ('network', 'raster_heavy', 'db')),
  enabled           boolean NOT NULL DEFAULT true,
  todo              text,
  yaml_path         text,                 -- NULL = the YAML file no longer exists (orphaned)
  yaml_sha256       text,
  yaml_text         text,                 -- for display; recipes never contain secrets
  synced_at         timestamptz NOT NULL DEFAULT now(),
  sync_error        text
);

-- Scheduling intent. Phase A: CLI runs create an inline job (claimed immediately).
-- Phase B adds the worker (FOR UPDATE SKIP LOCKED claims).
CREATE TABLE app.jobs (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  recipe_name       text REFERENCES app.recipes (name) ON UPDATE CASCADE ON DELETE SET NULL,
  action            text NOT NULL,
  params            jsonb NOT NULL DEFAULT '{}',
  priority          integer NOT NULL DEFAULT 100,
  concurrency_class text NOT NULL DEFAULT 'network' CHECK (concurrency_class IN ('network', 'raster_heavy', 'db')),
  status            text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancel_requested', 'cancelled')),
  attempts          integer NOT NULL DEFAULT 0,
  max_attempts      integer NOT NULL DEFAULT 4,
  run_after         timestamptz NOT NULL DEFAULT now(),
  locked_by         text,
  locked_at         timestamptz,
  heartbeat_at      timestamptz,
  finished_at       timestamptz,
  dedupe_key        text,
  created_by        text NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_queue_idx ON app.jobs (status, run_after, priority, id);
CREATE UNIQUE INDEX jobs_dedupe_idx ON app.jobs (dedupe_key) WHERE status IN ('queued', 'running') AND dedupe_key IS NOT NULL;

-- One execution attempt (CLI and UI runs look the same).
CREATE TABLE app.runs (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_id            bigint REFERENCES app.jobs (id) ON DELETE SET NULL,
  recipe_name       text REFERENCES app.recipes (name) ON UPDATE CASCADE ON DELETE SET NULL,  -- NULL = ad hoc
  action            text NOT NULL CHECK (action IN ('import', 'download', 'derive', 'reaggregate', 'freshness',
                                                    'healthcheck', 'dry_run', 'set_enabled', 'backfill')),
  params            jsonb NOT NULL DEFAULT '{}',
  status            text NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  outcome           text,                  -- e.g. 'replaced', 'unchanged'
  triggered_by      text NOT NULL,         -- 'cli:<user>', 'ui:<user>', 'schedule', 'backfill'
  host              text,
  started_at        timestamptz,
  finished_at       timestamptz,
  duration          interval GENERATED ALWAYS AS (finished_at - started_at) STORED,
  bytes_downloaded  bigint,
  rows_written      bigint,
  parts_total       integer,
  parts_done        integer,
  progress          numeric,
  log_tail          text,                  -- last ~16 KB, redacted
  error             text,                  -- redacted
  artefacts         jsonb NOT NULL DEFAULT '{}',
  report            jsonb NOT NULL DEFAULT '{}',
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX runs_recipe_idx ON app.runs (recipe_name, id DESC);

-- One dataset -> many outputs. postgis_table rows carry the import provenance that used to live in app.datasets.
CREATE TABLE app.dataset_outputs (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  recipe_name        text REFERENCES app.recipes (name) ON UPDATE CASCADE ON DELETE SET NULL,
  kind               text NOT NULL CHECK (kind IN ('postgis_table', 'pub_view', 'materialized_view',
                                                   'tipg_collection', 'cog', 'tile_url')),
  locator            text NOT NULL,        -- src_x.t | pub.v | tiPG collection id | data/cog path | URL template
  public_url         text,
  projects           text[] NOT NULL DEFAULT '{}',
  source             text,
  source_layer       text,
  source_sha256      text,
  source_srs         text,
  target_srs         text,
  geometry_type      text,
  srid               integer,
  row_count          bigint,
  invalid_geom_count bigint,
  raster             jsonb,
  bytes              bigint,
  checksum           text,
  loaded_vintage     text,
  loaded_run_id      bigint,
  license            text,
  notes              text,
  imported_at        timestamptz,
  imported_by        text DEFAULT current_user,
  footprint          geometry(MultiPolygon, 4326),
  bbox               box2d,
  health             text NOT NULL DEFAULT 'unknown' CHECK (health IN ('ok', 'warn', 'fail', 'unknown')),
  health_detail      text,
  health_checked_at  timestamptz,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, locator),
  CHECK (kind <> 'postgis_table' OR locator ~ '^src_[a-z0-9_]+\.')
);

-- Requested vs received coverage per dataset.
CREATE TABLE app.coverages (
  recipe_name     text PRIMARY KEY REFERENCES app.recipes (name) ON UPDATE CASCADE ON DELETE CASCADE,
  extent_name     text,
  spec            jsonb NOT NULL DEFAULT '{}',
  requested_geom  geometry(MultiPolygon, 4326),
  received_geom   geometry(MultiPolygon, 4326),
  missing_geom    geometry(MultiPolygon, 4326),
  bbox            box2d,
  received_ratio  numeric,
  computed_at     timestamptz
);

-- Datasets published in pieces (SSURGO survey areas, per-state files, DEM tiles).
-- Single-file datasets get one part with part_key '*' that carries the upstream version markers.
CREATE TABLE app.dataset_parts (
  id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  recipe_name            text NOT NULL REFERENCES app.recipes (name) ON UPDATE CASCADE ON DELETE CASCADE,
  part_key               text NOT NULL,
  part_kind              text,
  upstream_version       text,
  upstream_date          timestamptz,
  upstream_etag          text,
  upstream_last_modified text,
  upstream_bytes         bigint,
  loaded_version         text,
  loaded_date            timestamptz,
  loaded_run_id          bigint,
  checksum               text,
  bytes                  bigint,
  row_count              bigint,
  footprint              geometry(MultiPolygon, 4326),
  status                 text NOT NULL DEFAULT 'unknown'
                         CHECK (status IN ('current', 'stale', 'missing', 'loading', 'failed', 'excluded', 'unknown')),
  status_detail          text,
  checked_at             timestamptz,
  UNIQUE (recipe_name, part_key)
);

CREATE TABLE app.freshness_checks (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  recipe_name  text NOT NULL REFERENCES app.recipes (name) ON UPDATE CASCADE ON DELETE CASCADE,
  part_key     text,
  method       text NOT NULL,
  observed     jsonb NOT NULL DEFAULT '{}',
  verdict      text NOT NULL CHECK (verdict IN ('current', 'stale', 'unknown', 'error')),
  detail       text,
  checked_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX freshness_recipe_idx ON app.freshness_checks (recipe_name, checked_at DESC);

-- Only whether a key is configured: never the value. Written by the processes that hold keys (CLI, worker).
CREATE TABLE app.secrets_status (
  key_name         text PRIMARY KEY,
  configured       boolean NOT NULL,
  fingerprint      text,                   -- first 8 hex of sha256(value), to notice rotations
  required_by      text[] NOT NULL DEFAULT '{}',
  last_used_ok_at  timestamptz,
  last_error_at    timestamptz,
  last_error       text,
  reported_at      timestamptz NOT NULL DEFAULT now()
);

-- ---- move app.datasets (one row per imported src table) into the registry -------------------
INSERT INTO app.recipes (name, sync_error)
SELECT DISTINCT recipe, 'placeholder created by migration; run make recipes-sync'
FROM app.datasets WHERE recipe IS NOT NULL
ON CONFLICT DO NOTHING;

INSERT INTO app.dataset_outputs (recipe_name, kind, locator, source, source_layer, source_sha256, source_srs,
                                 target_srs, geometry_type, srid, row_count, invalid_geom_count, license, notes,
                                 imported_at, imported_by)
SELECT recipe, 'postgis_table', table_schema || '.' || table_name, source, source_layer, source_sha256, source_srs,
       target_srs, geometry_type, srid, row_count, invalid_geom_count, license, notes, imported_at, imported_by
FROM app.datasets;

-- History before runs existed: one synthesized run per imported table.
INSERT INTO app.runs (recipe_name, action, status, outcome, triggered_by, started_at, finished_at, rows_written, log_tail)
SELECT recipe, 'backfill', 'succeeded', 'recorded before run history existed', 'backfill', imported_at, imported_at,
       row_count, format('Imported %s.%s (%s rows) from %s by %s.', table_schema, table_name, row_count, source, imported_by)
FROM app.datasets;

UPDATE app.dataset_outputs o SET loaded_run_id = r.id
FROM app.runs r
WHERE r.action = 'backfill' AND o.kind = 'postgis_table'
  AND r.recipe_name IS NOT DISTINCT FROM o.recipe_name AND r.finished_at = o.imported_at;

DROP TABLE app.datasets;

CREATE VIEW app.datasets AS
SELECT id,
       split_part(locator, '.', 1) AS table_schema,
       split_part(locator, '.', 2) AS table_name,
       source, source_layer, source_sha256, source_srs, target_srs, geometry_type, srid,
       row_count, invalid_geom_count, recipe_name AS recipe, license, notes, imported_at, imported_by
FROM app.dataset_outputs
WHERE kind = 'postgis_table';
COMMENT ON VIEW app.datasets IS 'Compatibility view (pre-registry name). New code uses app.dataset_outputs.';

-- ---- grants ---------------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON
  app.recipes, app.jobs, app.runs, app.dataset_outputs, app.coverages,
  app.dataset_parts, app.freshness_checks, app.secrets_status
TO etl_runner;
GRANT SELECT ON
  app.recipes, app.jobs, app.runs, app.dataset_outputs, app.coverages,
  app.dataset_parts, app.freshness_checks, app.secrets_status
TO admin_api;
GRANT SELECT, DELETE ON app.datasets TO loader;
GRANT SELECT ON app.datasets, app.dataset_outputs TO worker_rw, analyst_ro;

-- migrate:down
CREATE TABLE app.datasets_old AS
SELECT split_part(locator, '.', 1) AS table_schema, split_part(locator, '.', 2) AS table_name,
       COALESCE(source, '') AS source, source_layer, source_sha256, source_srs, target_srs, geometry_type, srid,
       row_count, invalid_geom_count, recipe_name AS recipe, license, notes,
       COALESCE(imported_at, now()) AS imported_at, COALESCE(imported_by, current_user) AS imported_by
FROM app.dataset_outputs WHERE kind = 'postgis_table';
DROP VIEW app.datasets;
DROP TABLE app.secrets_status, app.freshness_checks, app.dataset_parts, app.coverages,
           app.dataset_outputs, app.runs, app.jobs, app.recipes;
CREATE TABLE app.datasets (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  table_schema       text NOT NULL,
  table_name         text NOT NULL,
  source             text NOT NULL,
  source_layer       text,
  source_sha256      text,
  source_srs         text,
  target_srs         text,
  geometry_type      text,
  srid               integer,
  row_count          bigint,
  invalid_geom_count bigint,
  recipe             text,
  license            text,
  notes              text,
  imported_at        timestamptz NOT NULL DEFAULT now(),
  imported_by        text NOT NULL DEFAULT current_user,
  UNIQUE (table_schema, table_name),
  CHECK (table_schema ~ '^src_')
);
INSERT INTO app.datasets (table_schema, table_name, source, source_layer, source_sha256, source_srs, target_srs,
                          geometry_type, srid, row_count, invalid_geom_count, recipe, license, notes, imported_at, imported_by)
SELECT * FROM app.datasets_old;
DROP TABLE app.datasets_old;
GRANT SELECT, INSERT, UPDATE, DELETE ON app.datasets TO loader;
GRANT SELECT ON app.datasets TO worker_rw, analyst_ro;
REVOKE etl_runner FROM loader;
DROP ROLE IF EXISTS etl_runner;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admin_api') THEN
    EXECUTE 'DROP OWNED BY admin_api';
    EXECUTE 'DROP ROLE admin_api';
  END IF;
END $$;
