-- Maine Places & Buildings: footprints -> pub.maine_places__buildings (Overture Maps buildings).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_places__buildings;
CREATE OR REPLACE VIEW pub.maine_places__buildings AS
SELECT id,
       name,
       replace(coalesce(class, subtype, 'unknown'), '_', ' ') AS kind,
       round(height::numeric, 1)::float8                      AS height_m,
       num_floors,
       geom AS geom
FROM src_overture.buildings;

COMMENT ON VIEW pub.maine_places__buildings IS 'maine-places: building footprints (Overture Maps)';
