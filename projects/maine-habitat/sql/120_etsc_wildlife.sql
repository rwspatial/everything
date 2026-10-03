-- Maine Habitat: endangered, threatened and special concern wildlife habitat (MDIFW, generalized).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__etsc_wildlife;
CREATE OR REPLACE VIEW pub.maine_habitat__etsc_wildlife AS
SELECT id, scomname AS common_name, sname AS scientific_name, sprot AS state_status, srank, last_obs_d AS last_observed, ST_Force2D(geom)::geometry(MultiPolygon, 4326) AS geom FROM src_habitat.etsc_wildlife;

COMMENT ON VIEW pub.maine_habitat__etsc_wildlife IS 'maine-habitat: endangered, threatened and special concern wildlife habitat (MDIFW)';
