-- Maine Habitat: Beginning with Habitat focus areas.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__focus_areas;
CREATE OR REPLACE VIEW pub.maine_habitat__focus_areas AS
SELECT id, fa_name AS name, mdifw_rgn AS region, geom AS geom FROM src_habitat.focus_areas;

COMMENT ON VIEW pub.maine_habitat__focus_areas IS 'maine-habitat: focus areas of statewide ecological significance (BwH)';
