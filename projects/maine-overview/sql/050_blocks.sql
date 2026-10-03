-- Maine Overview: 2020 census blocks -> pub.maine_overview__blocks (TABBLOCK20 joined to 2020 Census DHC counts).
-- Blocks come only from the decennial census. Density uses land area (ALAND20, m²); water-only blocks have none.
DROP VIEW IF EXISTS pub.maine_overview__blocks;
CREATE OR REPLACE VIEW pub.maine_overview__blocks AS
SELECT b.id,
       b.geoid20                                                          AS geoid,
       'Block ' || b.name20 || ', tract ' || ltrim(b.tractce20, '0')      AS name,
       d.pop::integer                                                     AS pop,
       d.housing_units::integer                                           AS housing_units,
       d.vacant_units::integer                                            AS vacant_units,
       CASE WHEN b.aland20 > 0 THEN round((d.pop / (b.aland20 / 2589988.11))::numeric, 1)::float8 END AS pop_per_sq_mi,
       b.geom
FROM src_census.block b
LEFT JOIN src_census.dec2020_block d ON d.geoid = b.geoid20;

COMMENT ON VIEW pub.maine_overview__blocks IS 'maine-overview: 2020 census blocks with population and housing counts';
