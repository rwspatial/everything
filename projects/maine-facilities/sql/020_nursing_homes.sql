-- Maine Critical Facilities: nursing homes and assisted living (HIFLD).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__nursing_homes;
CREATE OR REPLACE VIEW pub.maine_facilities__nursing_homes AS
SELECT id, initcap(name) AS name, initcap(type) AS type, beds::integer AS beds, initcap(city) AS city, telephone, geom AS geom
FROM src_hifld.nursing_homes WHERE coalesce(status, 'OPEN') = 'OPEN';

COMMENT ON VIEW pub.maine_facilities__nursing_homes IS 'maine-facilities: nursing homes and assisted living (HIFLD)';
