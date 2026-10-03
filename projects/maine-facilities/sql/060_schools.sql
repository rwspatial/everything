-- Maine Critical Facilities: public and private schools (HIFLD, NCES).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__schools;
CREATE OR REPLACE VIEW pub.maine_facilities__schools AS
SELECT 'pub-' || id AS id, initcap(name) AS name, 'public' AS kind, level_ AS level, st_grade || '–' || end_grade AS grades,
       nullif(enrollment, -999) AS enrollment, initcap(city) AS city, geom AS geom
FROM src_hifld.public_schools
UNION ALL
SELECT 'pri-' || id, initcap(name), 'private', level_, st_grade || '–' || end_grade, nullif(enrollment, -999), initcap(city), geom AS geom
FROM src_hifld.private_schools;

COMMENT ON VIEW pub.maine_facilities__schools IS 'maine-facilities: public and private K-12 schools (HIFLD / NCES)';
