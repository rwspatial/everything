-- Maine Soils: SSURGO map-unit polygons with their attributes -> pub.maine_soils__mapunits.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_soils__mapunits;
CREATE OR REPLACE VIEW pub.maine_soils__mapunits AS
SELECT p.id,
       p.mukey,
       p.areasymbol,
       p.musym,
       m.muname,
       coalesce(m.hydgrpdcd, 'not rated')          AS hsg,
       coalesce(m.drclassdcd, 'not rated')         AS drainage,
       m.farmlndcl                                 AS farmland,
       m.slopegradwta::float8                      AS slope_pct,
       m.brockdepmin::float8                       AS bedrock_cm,
       m.wtdepannmin::float8                       AS watertable_cm,
       m.flodfreqdcd                               AS flooding,
       m.niccdcd                                   AS capability_class,
       p.geom
FROM src_ssurgo.mupolygon p
JOIN src_ssurgo.mapunit m USING (mukey);

COMMENT ON VIEW pub.maine_soils__mapunits IS 'maine-soils: SSURGO soil map units with hydrologic group, drainage and farmland class (USDA-NRCS)';
