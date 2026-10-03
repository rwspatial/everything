-- Maine Critical Facilities: colleges and universities (HIFLD, IPEDS).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__colleges;
CREATE OR REPLACE VIEW pub.maine_facilities__colleges AS
SELECT id, initcap(name) AS name, sector, tot_enroll AS enrollment, initcap(city) AS city, website, ST_PointOnSurface(geom)::geometry(Point, 4326) AS geom
FROM src_hifld.colleges;

COMMENT ON VIEW pub.maine_facilities__colleges IS 'maine-facilities: colleges and universities (HIFLD / IPEDS)';
