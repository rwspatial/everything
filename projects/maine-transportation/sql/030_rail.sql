-- Maine Transportation: rail lines (USGS NTD from the FRA North American Rail Network).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__rail;
CREATE OR REPLACE VIEW pub.maine_transportation__rail AS
SELECT id, coalesce(nullif(name, ''), railsubdivision) AS name, railowner AS owner, railusage_desc AS usage,
       railclassification_desc AS fra_class, geom AS geom FROM src_ntd.rail;

COMMENT ON VIEW pub.maine_transportation__rail IS 'maine-transportation: railroads (USGS NTD / FRA)';
