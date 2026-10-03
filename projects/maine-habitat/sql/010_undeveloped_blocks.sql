-- Maine Habitat: Beginning with Habitat undeveloped habitat blocks.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__undeveloped_blocks;
CREATE OR REPLACE VIEW pub.maine_habitat__undeveloped_blocks AS
SELECT id, round(gis_acres::numeric)::float8 AS acres, geom AS geom FROM src_habitat.undeveloped_blocks;

COMMENT ON VIEW pub.maine_habitat__undeveloped_blocks IS 'maine-habitat: undeveloped habitat blocks (BwH)';
