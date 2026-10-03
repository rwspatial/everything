-- Maine Critical Facilities: fire and EMS stations (HIFLD).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__fire_ems;
CREATE OR REPLACE VIEW pub.maine_facilities__fire_ems AS
SELECT id, initcap(name) AS name, initcap(address) AS address, initcap(city) AS city, geom AS geom
FROM src_hifld.fire_ems;

COMMENT ON VIEW pub.maine_facilities__fire_ems IS 'maine-facilities: fire and EMS stations (HIFLD / USGS structures)';
