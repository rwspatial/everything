-- Maine Habitat: significant vernal pools and their habitat (MDIFW).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__vernal_pools;
CREATE OR REPLACE VIEW pub.maine_habitat__vernal_pools AS
SELECT id, poolid, svpstatus AS status, township, buffer_acres::float8 AS habitat_acres, geom AS geom FROM src_habitat.significant_vernal_pools;

COMMENT ON VIEW pub.maine_habitat__vernal_pools IS 'maine-habitat: significant vernal pools (MDIFW)';
