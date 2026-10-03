-- Maine Habitat: inland waterfowl and wading bird habitat, IWWH (MDIFW).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__inland_waterfowl;
CREATE OR REPLACE VIEW pub.maine_habitat__inland_waterfowl AS
SELECT id, iwwh_id, CASE rating WHEN 'H' THEN 'high' WHEN 'M' THEN 'moderate' ELSE rating END AS rating, total_acre::float8 AS acres, ST_Force2D(geom)::geometry(MultiPolygon, 4326) AS geom FROM src_habitat.inland_waterfowl_wading_bird;

COMMENT ON VIEW pub.maine_habitat__inland_waterfowl IS 'maine-habitat: inland waterfowl and wading bird habitat (MDIFW)';
