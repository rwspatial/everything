-- Maine Transportation: traffic signals (MaineDOT).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__traffic_signals;
CREATE OR REPLACE VIEW pub.maine_transportation__traffic_signals AS
SELECT id, intersection, signal_beacon AS kind, maintained_by, geom AS geom FROM src_mdot.traffic_signals;

COMMENT ON VIEW pub.maine_transportation__traffic_signals IS 'maine-transportation: traffic signals (MaineDOT)';
