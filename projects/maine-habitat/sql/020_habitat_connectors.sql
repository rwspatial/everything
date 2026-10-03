-- Maine Habitat: likely wildlife crossings between habitat blocks (BwH).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__habitat_connectors;
CREATE OR REPLACE VIEW pub.maine_habitat__habitat_connectors AS
SELECT id, length_feet_corrected::float8 AS length_ft, riparian_or_wetland, geom AS geom FROM src_habitat.habitat_connectors;

COMMENT ON VIEW pub.maine_habitat__habitat_connectors IS 'maine-habitat: habitat connectors (BwH)';
