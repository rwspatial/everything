-- migrate:up
-- Per-service login roles and least-privilege grants.
-- Passwords are NOT set here; the migrator sets them from .env afterwards
-- (db/roles/set-passwords.sql). Nothing here needs a superuser, so it also runs on RDS.
--
--   role        | used by              | can
--   ------------+----------------------+------------------------------------------------
--   tipg_ro     | tipg                 | read pub views, execute pub functions. Nothing else
--   app_rw      | core-api (Phase 3)   | read/write app.*, read pub
--   loader      | geotools imports     | create/replace tables in src_*, write app.datasets
--   worker_rw   | ML workers (Phase 5) | read src_* and pub, write ml_out
--   analyst_ro  | make r / make py     | read src_*, pub, ml_out, app.datasets
--   src_reader  | (group, no login)    | SELECT on every src_* table

DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['tipg_ro', 'app_rw', 'loader', 'worker_rw', 'analyst_ro'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN', r);
    END IF;
  END LOOP;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'src_reader') THEN
    CREATE ROLE src_reader NOLOGIN;
  END IF;
  -- The migration role owns the pub views, which read loader-owned src_* tables.
  -- Membership in loader is required to set loader's default privileges.
  EXECUTE format('GRANT src_reader TO %I', current_user);
  EXECUTE format('GRANT loader TO %I', current_user);
END $$;

GRANT src_reader TO worker_rw, analyst_ro;

-- Functions created by the migration role are not executable by PUBLIC by default.
-- (Must be global: schema-level default privileges cannot revoke.)
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- pub: the publication surface
GRANT USAGE ON SCHEMA pub TO tipg_ro, app_rw, worker_rw, analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA pub GRANT SELECT ON TABLES TO tipg_ro, app_rw, worker_rw, analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA pub GRANT EXECUTE ON FUNCTIONS TO tipg_ro, app_rw, worker_rw, analyst_ro;

-- app: registry + provenance (table-specific grants live with each table)
GRANT USAGE ON SCHEMA app TO app_rw, loader, worker_rw, analyst_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT USAGE, SELECT ON SEQUENCES TO app_rw;

-- ml_out: worker outputs (Phase 5)
GRANT USAGE, CREATE ON SCHEMA ml_out TO worker_rw;
GRANT USAGE ON SCHEMA ml_out TO analyst_ro;

-- Source schemas. To add a new domain later, write a migration that calls:
--   CALL app.ensure_src_schema('src_<domain>');
CREATE OR REPLACE PROCEDURE app.ensure_src_schema(schema_name text)
LANGUAGE plpgsql
AS $$
BEGIN
  IF schema_name !~ '^src_[a-z][a-z0-9_]*$' THEN
    RAISE EXCEPTION 'source schemas must be named src_<name> (lowercase), got %', schema_name;
  END IF;
  EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', schema_name);
  EXECUTE format('COMMENT ON SCHEMA %I IS %L', schema_name,
                 'Source data loaded by the loader role (make import). Never served directly.');
  EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO loader', schema_name);
  EXECUTE format('GRANT USAGE ON SCHEMA %I TO src_reader', schema_name);
  EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE loader IN SCHEMA %I GRANT SELECT ON TABLES TO src_reader',
                 schema_name);
END
$$;

CALL app.ensure_src_schema('src_ne');     -- Natural Earth (placeholder projects)
CALL app.ensure_src_schema('src_hydro');  -- hydrology domain (hydrology-sketch todo layers)

-- migrate:down
DROP SCHEMA IF EXISTS src_hydro CASCADE;
DROP SCHEMA IF EXISTS src_ne CASCADE;
DROP PROCEDURE IF EXISTS app.ensure_src_schema(text);
ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
DO $$
DECLARE
  r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['tipg_ro', 'app_rw', 'loader', 'worker_rw', 'analyst_ro', 'src_reader'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('DROP OWNED BY %I', r);
      EXECUTE format('DROP ROLE %I', r);
    END IF;
  END LOOP;
END $$;
