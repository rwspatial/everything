-- Maine Lands: trails and paths from OpenStreetMap (via Overture Maps; recipe me_overture_trails). Footpaths, hiking and
-- multi-use paths, cycleways and bridleways; sidewalks, crosswalks and tracks (logging roads) are left out at import.
-- About ten times the mileage of the USGS National Digital Trails, including town, land-trust and campus trails.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_lands__osm_trails;
CREATE VIEW pub.maine_lands__osm_trails AS
SELECT id,
       coalesce(nullif(name, ''), 'Unnamed trail') AS name,
       CASE class WHEN 'path' THEN 'Hiking / multi-use path' WHEN 'footway' THEN 'Footpath'
                  WHEN 'cycleway' THEN 'Bike path' WHEN 'bridleway' THEN 'Bridle path' ELSE class END AS trail_class,
       CASE WHEN surface IN ('paved', 'asphalt', 'concrete', 'paving_stones', 'metal', 'wood') THEN 'Paved'
            WHEN surface IN ('unpaved', 'dirt', 'gravel', 'ground', 'grass', 'compacted', 'sand') THEN 'Unpaved'
            ELSE 'Unknown' END AS surface,
       (ST_Length(geom::geography) / 1609.344)::float8 AS miles,
       geom
FROM src_overture.trails;

COMMENT ON VIEW pub.maine_lands__osm_trails IS 'maine-lands: trails and paths (OpenStreetMap via Overture Maps, no sidewalks or tracks)';
