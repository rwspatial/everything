-- Maine Habitat: deer wintering areas (MDIFW).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__deer_wintering_areas;
CREATE OR REPLACE VIEW pub.maine_habitat__deer_wintering_areas AS
SELECT id, identifier, ST_Force2D(geom)::geometry(MultiPolygon, 4326) AS geom FROM src_habitat.deer_wintering_areas;

COMMENT ON VIEW pub.maine_habitat__deer_wintering_areas IS 'maine-habitat: deer wintering areas (MDIFW)';
