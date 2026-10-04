-- Maine Places & Buildings: footprints -> pub.maine_places__buildings (Overture Maps buildings), coloured by category
-- (Overture subtype, grouped); class is the finer type shown on click.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_places__buildings;
CREATE OR REPLACE VIEW pub.maine_places__buildings AS
SELECT id,
       name,
       replace(coalesce(class, subtype, 'unknown'), '_', ' ') AS kind,
       -- The map's colour: Overture's subtype grouped into a few readable categories (89 % of footprints have none).
       CASE subtype
         WHEN 'residential' THEN 'Residential'
         WHEN 'commercial' THEN 'Commercial'
         WHEN 'agricultural' THEN 'Agricultural'
         WHEN 'education' THEN 'Education'
         WHEN 'medical' THEN 'Medical'
         WHEN 'civic' THEN 'Civic & religious'
         WHEN 'religious' THEN 'Civic & religious'
         WHEN 'industrial' THEN 'Industrial & service'
         WHEN 'service' THEN 'Industrial & service'
         ELSE CASE WHEN subtype IS NULL THEN 'Unknown' ELSE 'Other' END   -- transportation, entertainment, outbuildings
       END                                                    AS category,
       replace(subtype, '_', ' ')                             AS subtype,
       replace(class, '_', ' ')                               AS class,
       round(height::numeric, 1)::float8                      AS height_m,
       num_floors,
       geom AS geom
FROM src_overture.buildings;

COMMENT ON VIEW pub.maine_places__buildings IS 'maine-places: building footprints (Overture Maps)';
