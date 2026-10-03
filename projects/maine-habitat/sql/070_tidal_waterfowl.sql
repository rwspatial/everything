-- Maine Habitat: tidal waterfowl and wading bird habitat, TWWH (MDIFW).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__tidal_waterfowl;
CREATE OR REPLACE VIEW pub.maine_habitat__tidal_waterfowl AS
SELECT id, twwh_id, lower(value) AS value, habitat, acres::float8 AS acres, geom AS geom FROM src_habitat.tidal_waterfowl_wading_bird;

COMMENT ON VIEW pub.maine_habitat__tidal_waterfowl IS 'maine-habitat: tidal waterfowl and wading bird habitat (MDIFW)';
