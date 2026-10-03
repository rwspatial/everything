-- Maine Energy: electric transmission lines (EIA Energy Atlas / HIFLD).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_energy__transmission_lines;
CREATE OR REPLACE VIEW pub.maine_energy__transmission_lines AS
SELECT id, owner, voltage::float8 AS voltage_kv, volt_class, status, sub_1, sub_2, geom AS geom
FROM src_energy.transmission_lines;

COMMENT ON VIEW pub.maine_energy__transmission_lines IS 'maine-energy: electric transmission lines';
