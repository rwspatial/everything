-- Maine Transportation: posted speed limits (MaineDOT).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__speed_limits;
CREATE OR REPLACE VIEW pub.maine_transportation__speed_limits AS
SELECT id, speed::integer AS mph, comments, geom AS geom FROM src_mdot.posted_speed_limits;

COMMENT ON VIEW pub.maine_transportation__speed_limits IS 'maine-transportation: posted speed limits (MaineDOT)';
