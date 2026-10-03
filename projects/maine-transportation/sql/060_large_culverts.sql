-- Maine Transportation: large culverts with condition (MaineDOT).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__large_culverts;
CREATE OR REPLACE VIEW pub.maine_transportation__large_culverts AS
SELECT id, route, begin_town AS town, barrel_structure_type AS structure, lower(barrel_condition) AS condition,
       span_width::float8 AS span_ft, length::float8 AS length_ft, last_inspect_date::date AS last_inspected, geom AS geom
FROM src_mdot.large_culverts;

COMMENT ON VIEW pub.maine_transportation__large_culverts IS 'maine-transportation: large culverts (MaineDOT)';
