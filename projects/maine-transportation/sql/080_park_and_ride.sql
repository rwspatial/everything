-- Maine Transportation: park and ride lots (MaineDOT).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__park_and_ride;
CREATE OR REPLACE VIEW pub.maine_transportation__park_and_ride AS
SELECT id, location, begin_town AS town, total_num_spaces AS spaces, transit_other_services AS transit,
       geom::geometry(Point, 4326) AS geom FROM src_mdot.park_and_ride;

COMMENT ON VIEW pub.maine_transportation__park_and_ride IS 'maine-transportation: park and ride lots (MaineDOT)';
