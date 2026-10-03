-- migrate:up
-- Overture Maps Foundation themes for Maine (buildings, places), snapshotted from the public GeoParquet release.
CALL app.ensure_src_schema('src_overture');

-- migrate:down
DROP SCHEMA IF EXISTS src_overture CASCADE;
