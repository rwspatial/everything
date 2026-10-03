-- Maine Transportation: highway-rail grade crossings (MaineDOT).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__railroad_crossings;
CREATE OR REPLACE VIEW pub.maine_transportation__railroad_crossings AS
SELECT id, federal_crossing_number, intersecting_road AS road, begin_town AS town, crossing_type, signalized,
       crossing_surface_cond AS surface_condition, geom AS geom FROM src_mdot.railroad_crossings;

COMMENT ON VIEW pub.maine_transportation__railroad_crossings IS 'maine-transportation: railroad crossings (MaineDOT)';
