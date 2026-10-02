-- migrate:up
-- Phase 5: R/Python analysis processes on the same job queue the dataset worker will use (admin plan Phase B).
--
--   app.processes   descriptors that workers register at start-up (contracts/process.v1.schema.json)
--   app.jobs        + kind 'process': process_id, inputs, progress, result (a LayerSpec + report), error
--   ml_out.job_<id> a job's output table (owned by worker_rw)
--   pub.analysis_sandbox__job_<id>  its published view, created only by app.publish_job_layer (SECURITY DEFINER)
--
--   role      | rights added here
--   worker_rw | register processes; claim/update jobs; publish its own output via app.publish_job_layer
--   app_rw    | core-api: read processes; create jobs; request cancellation (status column only)
--   admin_api | read processes

CREATE TABLE app.processes (
    id            text PRIMARY KEY CHECK (id ~ '^(py|r)\.[a-z0-9_]+$'),
    runtime       text NOT NULL CHECK (runtime IN ('python', 'r')),
    version       text NOT NULL,
    title         text NOT NULL,
    description   text,
    descriptor    jsonb NOT NULL,
    registered_by text NOT NULL,                 -- worker id (host:pid)
    registered_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE app.jobs
    ADD COLUMN kind text NOT NULL DEFAULT 'dataset' CHECK (kind IN ('dataset', 'process')),
    ADD COLUMN process_id text REFERENCES app.processes (id) ON UPDATE CASCADE ON DELETE SET NULL,
    ADD COLUMN inputs jsonb,
    ADD COLUMN progress real CHECK (progress BETWEEN 0 AND 1),
    ADD COLUMN progress_message text,
    ADD COLUMN started_at timestamptz,
    ADD COLUMN result jsonb,
    ADD COLUMN error jsonb,
    ADD CONSTRAINT jobs_process_has_id CHECK (kind <> 'process' OR process_id IS NOT NULL);
ALTER TABLE app.jobs DROP CONSTRAINT jobs_concurrency_class_check;
ALTER TABLE app.jobs ADD CONSTRAINT jobs_concurrency_class_check
    CHECK (concurrency_class IN ('network', 'raster_heavy', 'db', 'analysis'));
CREATE INDEX jobs_kind_queue_idx ON app.jobs (kind, status, run_after, priority, id);

GRANT SELECT, INSERT, UPDATE ON app.processes TO worker_rw;
GRANT SELECT, UPDATE ON app.jobs TO worker_rw;
GRANT SELECT ON app.processes TO app_rw, admin_api;
GRANT SELECT, INSERT ON app.jobs TO app_rw;
GRANT UPDATE (status) ON app.jobs TO app_rw;     -- cancellation requests only
GRANT USAGE ON SEQUENCE app.jobs_id_seq TO app_rw;

-- Publish a job's output table as a pub view tiPG can serve. Runs as the owner (so the default pub grants apply)
-- but only for a running process job whose ml_out.job_<id> has an id column and one geometry column with an SRID.
CREATE OR REPLACE FUNCTION app.publish_job_layer(p_job_id bigint) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
  tbl text := format('job_%s', p_job_id);
  vw  text := format('analysis_sandbox__job_%s', p_job_id);
  rel oid;
  n_geom int;
  srid int;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM app.jobs WHERE id = p_job_id AND kind = 'process' AND status = 'running') THEN
    RAISE EXCEPTION 'job % is not a running process job', p_job_id;
  END IF;
  rel := to_regclass(format('ml_out.%I', tbl));
  IF rel IS NULL THEN
    RAISE EXCEPTION 'ml_out.% does not exist', tbl;
  END IF;
  SELECT count(*), min(postgis_typmod_srid(a.atttypmod)) INTO n_geom, srid FROM pg_attribute a
   WHERE a.attrelid = rel AND a.atttypid = 'geometry'::regtype AND a.attnum > 0 AND NOT a.attisdropped;
  IF n_geom <> 1 OR coalesce(srid, 0) = 0 THEN
    RAISE EXCEPTION 'ml_out.% needs exactly one geometry column with a declared SRID', tbl;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = rel AND attname = 'id' AND NOT attisdropped) THEN
    RAISE EXCEPTION 'ml_out.% needs an id column', tbl;
  END IF;
  EXECUTE format('CREATE OR REPLACE VIEW pub.%I AS SELECT * FROM ml_out.%I', vw, tbl);
  EXECUTE format('COMMENT ON VIEW pub.%I IS %L', vw, format('analysis-sandbox: output of analysis job %s', p_job_id));
  RETURN 'pub.' || vw;
END
$$;
REVOKE ALL ON FUNCTION app.publish_job_layer(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.publish_job_layer(bigint) TO worker_rw;

-- Remove a job's published view and output table (cleanup, failed jobs, tests).
CREATE OR REPLACE FUNCTION app.discard_job_output(p_job_id bigint) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
  EXECUTE format('DROP VIEW IF EXISTS pub.%I', format('analysis_sandbox__job_%s', p_job_id));
  EXECUTE format('DROP TABLE IF EXISTS ml_out.%I', format('job_%s', p_job_id));
END
$$;
REVOKE ALL ON FUNCTION app.discard_job_output(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.discard_job_output(bigint) TO worker_rw, app_rw;

-- migrate:down
DROP FUNCTION IF EXISTS app.discard_job_output(bigint);
DROP FUNCTION IF EXISTS app.publish_job_layer(bigint);
DROP INDEX IF EXISTS app.jobs_kind_queue_idx;
ALTER TABLE app.jobs DROP CONSTRAINT IF EXISTS jobs_concurrency_class_check;
ALTER TABLE app.jobs ADD CONSTRAINT jobs_concurrency_class_check CHECK (concurrency_class IN ('network', 'raster_heavy', 'db'));
ALTER TABLE app.jobs DROP CONSTRAINT IF EXISTS jobs_process_has_id,
    DROP COLUMN IF EXISTS error, DROP COLUMN IF EXISTS result, DROP COLUMN IF EXISTS started_at,
    DROP COLUMN IF EXISTS progress_message, DROP COLUMN IF EXISTS progress, DROP COLUMN IF EXISTS inputs,
    DROP COLUMN IF EXISTS process_id, DROP COLUMN IF EXISTS kind;
DROP TABLE IF EXISTS app.processes;
