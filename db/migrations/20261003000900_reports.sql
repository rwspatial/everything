-- migrate:up
-- PDF reports (plan: project-builder §1.6). An admin queues a `report` job; the reporter service (headless
-- Chromium, services/reporter) prints /p/<slug>/report to data/reports/<slug>/<job>.pdf and records it here.
-- core-api lists and serves the files (public, like the maps); only admins can queue one.
--
--   role      | used by                            | rights here
--   worker_rw | reporter (and the analysis worker) | claim/update report jobs, record reports
--   app_rw    | core-api                           | queue report jobs (existing INSERT on app.jobs), read reports
--   admin_api | core-api (dashboard)               | read reports

ALTER TABLE app.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE app.jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ('dataset', 'process', 'report'));
ALTER TABLE app.jobs DROP CONSTRAINT jobs_concurrency_class_check;
ALTER TABLE app.jobs ADD CONSTRAINT jobs_concurrency_class_check
    CHECK (concurrency_class IN ('network', 'raster_heavy', 'db', 'analysis', 'report'));

CREATE TABLE app.reports (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug             text NOT NULL REFERENCES app.projects (slug) ON DELETE CASCADE,
    job_id           bigint REFERENCES app.jobs (id) ON DELETE SET NULL,
    path             text NOT NULL CHECK (path ~ '^[a-z0-9-]+/[0-9]+\.pdf$'),   -- under data/reports/
    bytes            bigint NOT NULL,
    pages            integer,
    manifest_version integer,
    created_at       timestamptz NOT NULL DEFAULT now(),
    created_by       text NOT NULL
);
CREATE INDEX reports_slug_idx ON app.reports (slug, created_at DESC);

GRANT SELECT, INSERT ON app.reports TO worker_rw;
GRANT SELECT ON app.reports TO app_rw, admin_api;
GRANT SELECT ON app.projects TO worker_rw;     -- the reporter reads the manifest version it printed

-- migrate:down
DROP TABLE IF EXISTS app.reports;
DELETE FROM app.jobs WHERE kind = 'report';
ALTER TABLE app.jobs DROP CONSTRAINT jobs_concurrency_class_check;
ALTER TABLE app.jobs ADD CONSTRAINT jobs_concurrency_class_check
    CHECK (concurrency_class IN ('network', 'raster_heavy', 'db', 'analysis'));
ALTER TABLE app.jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE app.jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ('dataset', 'process'));
