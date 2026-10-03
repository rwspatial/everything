-- Maine Lands: town and township boundaries, Maine GeoLibrary.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_lands__town_boundaries;
CREATE OR REPLACE VIEW pub.maine_lands__town_boundaries AS
SELECT id, town, county, type, geom AS geom
FROM src_megis.towns WHERE land = 'y';

COMMENT ON VIEW pub.maine_lands__town_boundaries IS 'maine-lands: town and township boundaries (MEGIS)';
