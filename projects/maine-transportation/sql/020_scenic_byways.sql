-- Maine Transportation: state and national scenic byways (MaineDOT).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__scenic_byways;
CREATE OR REPLACE VIEW pub.maine_transportation__scenic_byways AS
SELECT id, sb_name AS name, designation_type_decode AS designation, existing_or_proposed_decode AS status, description, geom AS geom FROM src_mdot.scenic_byways;

COMMENT ON VIEW pub.maine_transportation__scenic_byways IS 'maine-transportation: scenic byways (MaineDOT)';
