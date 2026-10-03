-- Maine Lands: tax parcels, Maine GeoLibrary (MEGIS). Organized towns (municipal tax maps) and the
-- Unorganized Territory (Maine Revenue Services) in one layer; drawn from zoom 13 only (745k polygons).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
-- geom is passed through unwrapped (both sources are already 2D MultiPolygon 4326): an expression such as
-- ST_Force2D(geom) hides the GiST index from tiPG's tile filter and makes every tile scan all 745k rows.
DROP VIEW IF EXISTS pub.maine_lands__parcels;
CREATE OR REPLACE VIEW pub.maine_lands__parcels AS
SELECT id, area, town, map_lot, acres,
       -- `label` is the whole popup line: templates can't skip empty fields.
       concat_ws(', ', address, 'map/lot ' || map_lot, town)
         || coalesce(': ' || CASE WHEN acres < 0.1 THEN 'under 0.1' ELSE round(acres::numeric, 1)::text END
                     || acres_kind, '') AS label,
       geom
FROM (
  -- Organized towns: acres are mapped area (shape__area is true m², checked against ST_Area(geography)).
  SELECT id, 'organized'::text AS area, town, nullif(regexp_replace(trim(map_bk_lot), '\s+', ' ', 'g'), '') AS map_lot,
         nullif(regexp_replace(regexp_replace(trim(prop_loc), '^0+(\d)', '\1'), '^0 ', ''), '') AS address,
         (shape__area / 4046.8564224)::float8 AS acres, ' acres' AS acres_kind, geom
  FROM src_megis.parcels_organized
  UNION ALL
  -- Unorganized Territory: `town` is an MRS code (e.g. FRP03), so name the township from the town layer;
  -- acres are the recorded totacres where present (about 1 in 10), otherwise mapped area.
  SELECT 10000000 + u.id, 'unorganized', coalesce(t.town, u.town),
         nullif(regexp_replace(trim(coalesce(u.plan_lot, u.lot)), '\s+', ' ', 'g'), ''), NULL,
         coalesce(nullif(u.totacres, 0), ST_Area(u.geom::geography) / 4046.8564224)::float8,
         CASE WHEN nullif(u.totacres, 0) IS NULL THEN ' acres' ELSE ' recorded acres' END, u.geom
  FROM src_megis.parcels_unorganized u
  LEFT JOIN LATERAL (
    SELECT t.town FROM src_megis.towns t
    WHERE t.land = 'y' AND ST_Intersects(t.geom, ST_PointOnSurface(u.geom)) LIMIT 1
  ) t ON true
) p;

COMMENT ON VIEW pub.maine_lands__parcels IS 'maine-lands: tax parcels, organized towns and Unorganized Territory (MEGIS)';
