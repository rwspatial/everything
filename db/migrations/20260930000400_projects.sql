-- migrate:up
-- Project registry (plan §2.5, Phase 3). projects/<slug>/project.json in git stays the source of truth for
-- hand-edited projects; `mapgen apply/sync` registers them here, and the /new wizard saves here first
-- (`mapgen export` then writes the file). core-api serves the hub and viewer from these tables.
--
-- The manifest is stored as `json`, not `jsonb`: json keeps key order and formatting, so a manifest
-- exported back to a file is byte-identical to what was saved.
--
--   role      | used by                          | rights here
--   app_rw    | core-api (/api/projects), mapgen | read + write projects and their versions; read pub
--   admin_api | core-api (/api/admin)            | read projects (dashboard)

CREATE TABLE app.projects (
    slug        text PRIMARY KEY CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    title       text NOT NULL,
    status      text NOT NULL CHECK (status IN ('stub', 'draft', 'ready')),
    position    integer NOT NULL DEFAULT 1000,            -- hub order (projects/index.json order)
    manifest    json NOT NULL,
    checksum    text NOT NULL,                            -- sha256 of the normalized manifest text
    version     integer NOT NULL DEFAULT 1,
    origin      text NOT NULL CHECK (origin IN ('file', 'api')),  -- where the current version came from
    validation  jsonb,                                    -- report from contracts/validate.py at save time
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NOT NULL
);

CREATE TABLE app.manifest_versions (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug        text NOT NULL REFERENCES app.projects (slug) ON DELETE CASCADE,
    version     integer NOT NULL,
    manifest    json NOT NULL,
    checksum    text NOT NULL,
    origin      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text NOT NULL,
    UNIQUE (slug, version)
);

-- app_rw was created in Phase 1 for core-api with DML on every app table (default privileges). Narrow it:
-- the dataset registry is written only by loader/etl_runner, so its audit trail can be trusted.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA app FROM app_rw;
ALTER DEFAULT PRIVILEGES IN SCHEMA app REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLES FROM app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON app.projects TO app_rw;
GRANT SELECT, INSERT ON app.manifest_versions TO app_rw;
GRANT SELECT ON app.projects, app.manifest_versions TO admin_api;

-- migrate:down
DROP TABLE IF EXISTS app.manifest_versions;
DROP TABLE IF EXISTS app.projects;
ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT INSERT, UPDATE, DELETE ON TABLES TO app_rw;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO app_rw;
