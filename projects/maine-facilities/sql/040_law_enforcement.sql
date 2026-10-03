-- Maine Critical Facilities: local law enforcement (HIFLD).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__law_enforcement;
CREATE OR REPLACE VIEW pub.maine_facilities__law_enforcement AS
SELECT id, initcap(name) AS name, initcap(type) AS type, ftsworn AS sworn_officers, initcap(city) AS city, telephone, geom AS geom
FROM src_hifld.law_enforcement;

COMMENT ON VIEW pub.maine_facilities__law_enforcement IS 'maine-facilities: local law enforcement (HIFLD)';
