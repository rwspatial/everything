-- migrate:up
-- Keep a process descriptor's key order (its inputs are shown as a form in that order). jsonb sorts keys; json keeps
-- them as written, like app.projects.manifest. Workers re-register their descriptors at start-up.
ALTER TABLE app.processes ALTER COLUMN descriptor TYPE json USING descriptor::json;

-- migrate:down
ALTER TABLE app.processes ALTER COLUMN descriptor TYPE jsonb USING descriptor::jsonb;
