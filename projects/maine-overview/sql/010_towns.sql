-- Maine Overview: Median household income by town -> pub.maine_overview__towns
-- Applied by `./mapgen apply maine-overview` (and by `make seed`), as the database owner, so tiPG's grants apply.
-- Towns (TIGER/Line 2024 county subdivisions) joined to ACS 2020-2024 5-year estimates on GEOID.
-- Income is NULL where the Census Bureau suppresses the estimate (33 very small places).
CREATE OR REPLACE VIEW pub.maine_overview__towns AS
SELECT c.id,
       c.geoid,
       c.name,
       c.namelsad,
       split_part(a.name, ', ', 2)          AS county,
       a.pop::integer                       AS pop,
       a.median_hh_income::integer          AS median_hh_income,
       a.median_hh_income_moe::integer      AS median_hh_income_moe,
       c.geom
FROM src_census.cousub c
LEFT JOIN src_census.acs5_2024_cousub a USING (geoid);

COMMENT ON VIEW pub.maine_overview__towns IS 'maine-overview: median household income by town (ACS 2020-2024 5-year)';
