-- migrate:up
-- Provenance for every table loaded by `make import` (scripts/geoimport.py upserts here).
CREATE TABLE app.datasets (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  table_schema       text        NOT NULL,
  table_name         text        NOT NULL,
  source             text        NOT NULL,  -- file path under data/incoming, or URL
  source_layer       text,
  source_sha256      text,
  source_srs         text,                  -- e.g. EPSG:4269, or WKT name if no code
  target_srs         text,                  -- e.g. EPSG:4326, or 'native'
  geometry_type      text,                  -- as registered in geometry_columns
  srid               integer,
  row_count          bigint,
  invalid_geom_count bigint,
  recipe             text,                  -- data/recipes/<recipe>.yaml, NULL for ad hoc imports
  license            text,
  notes              text,
  imported_at        timestamptz NOT NULL DEFAULT now(),
  imported_by        text        NOT NULL DEFAULT current_user,
  UNIQUE (table_schema, table_name),
  CHECK (table_schema ~ '^src_')
);
COMMENT ON TABLE app.datasets IS 'One row per imported source table. Rows with recipe IS NULL are lost on make reset-db.';

GRANT SELECT, INSERT, UPDATE, DELETE ON app.datasets TO loader;
GRANT SELECT ON app.datasets TO worker_rw, analyst_ro;

-- migrate:down
DROP TABLE IF EXISTS app.datasets;
