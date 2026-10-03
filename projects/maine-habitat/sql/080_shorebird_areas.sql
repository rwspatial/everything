-- Maine Habitat: shorebird feeding and roosting areas (MDIFW).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__shorebird_areas;
CREATE OR REPLACE VIEW pub.maine_habitat__shorebird_areas AS
SELECT id, sitenum, use_ AS use, acres::float8 AS acres, geom AS geom FROM src_habitat.shorebird_areas;

COMMENT ON VIEW pub.maine_habitat__shorebird_areas IS 'maine-habitat: shorebird areas (MDIFW)';
