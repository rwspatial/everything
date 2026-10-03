-- Maine Transportation: airports, heliports and seaplane bases (USGS NTD).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__airports;
CREATE OR REPLACE VIEW pub.maine_transportation__airports AS
SELECT id, name, faa_airport_code AS faa_code,
       CASE fcode WHEN 20000 THEN 'airport' WHEN 20001 THEN 'heliport' WHEN 20002 THEN 'seaplane base' END AS kind,
       ownership_desc AS ownership, geom AS geom FROM src_ntd.airports WHERE fcode IN (20000, 20001, 20002);

COMMENT ON VIEW pub.maine_transportation__airports IS 'maine-transportation: airports, heliports and seaplane bases (USGS NTD)';
