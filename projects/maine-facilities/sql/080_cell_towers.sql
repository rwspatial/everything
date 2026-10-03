-- Maine Critical Facilities: cellular towers (HIFLD, FCC).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__cell_towers;
CREATE OR REPLACE VIEW pub.maine_facilities__cell_towers AS
SELECT id, licensee, structype AS structure, allstruc::float8 AS height_m, callsign, initcap(loccity) AS city, ST_PointOnSurface(geom)::geometry(Point, 4326) AS geom
FROM src_hifld.cell_towers;

COMMENT ON VIEW pub.maine_facilities__cell_towers IS 'maine-facilities: cellular towers (FCC licenses via HIFLD)';
