-- Maine Critical Facilities: open hospitals (HIFLD).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__hospitals;
CREATE OR REPLACE VIEW pub.maine_facilities__hospitals AS
SELECT id, initcap(name) AS name, initcap(type) AS type, beds::integer AS beds, trauma, initcap(city) AS city, telephone, website, ST_PointOnSurface(geom)::geometry(Point, 4326) AS geom
FROM src_hifld.hospitals WHERE status = 'OPEN';

COMMENT ON VIEW pub.maine_facilities__hospitals IS 'maine-facilities: hospitals (HIFLD)';
