-- Maine Energy: power plants (EIA Energy Atlas).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_energy__power_plants;
CREATE OR REPLACE VIEW pub.maine_energy__power_plants AS
SELECT id, plant_name AS name, primsource AS source, tech_desc AS technology, total_mw::float8 AS total_mw, utility_na AS operator,
       city, period, geom::geometry(Point, 4326) AS geom
FROM src_energy.power_plants WHERE state = 'Maine';

COMMENT ON VIEW pub.maine_energy__power_plants IS 'maine-energy: power plants (EIA-860)';
