-- Maine Places & Buildings: points of interest -> pub.maine_places__places (Overture Maps places, open, confidence >= 0.6).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_places__places;
CREATE OR REPLACE VIEW pub.maine_places__places AS
SELECT id,
       name,
       coalesce(nullif(top_category, ''), 'other')          AS category,
       replace(category, '_', ' ')                          AS detail,
       round(confidence::numeric, 2)::float8                AS confidence,
       address,
       locality,
       website,
       geom         AS geom
FROM src_overture.places;

COMMENT ON VIEW pub.maine_places__places IS 'maine-places: points of interest (Overture Maps)';
