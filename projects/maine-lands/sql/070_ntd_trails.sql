-- Maine Lands: trails from the USGS National Digital Trails / NTD.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_lands__ntd_trails;
CREATE OR REPLACE VIEW pub.maine_lands__ntd_trails AS
SELECT id, coalesce(nullif(name, ''), maplabel, 'Trail') AS name, trailtype_desc AS trail_type, lengthmiles::float8 AS miles,
       hikerpedestrian_desc AS hiking, bicycle_desc AS biking, crosscountryski_desc AS xc_ski, osvm_desc AS snowmobile,
       primarytrailmaintainer_desc AS maintainer, geom AS geom
FROM src_ntd.trails;

COMMENT ON VIEW pub.maine_lands__ntd_trails IS 'maine-lands: trails (USGS National Transportation Dataset)';
