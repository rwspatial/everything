-- Maine Habitat: seabird nesting islands (MDIFW).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__seabird_islands;
CREATE OR REPLACE VIEW pub.maine_habitat__seabird_islands AS
SELECT id, coalesce(name, islandid) AS name, owner, acres::float8 AS acres, geom AS geom FROM src_habitat.seabird_nesting_islands;

COMMENT ON VIEW pub.maine_habitat__seabird_islands IS 'maine-habitat: seabird nesting islands (MDIFW)';
