-- Maine Overview: census tracts -> pub.maine_overview__tracts (TIGER/Line 2024 joined to ACS 2020-2024 on GEOID).
-- Estimates are NULL where the Census Bureau suppresses them (very small or unpopulated tracts).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_overview__tracts;
CREATE OR REPLACE VIEW pub.maine_overview__tracts AS
SELECT t.id,
       t.geoid,
       t.namelsad                                                         AS name,
       split_part(a.name, '; ', 2)                                        AS county,
       a.pop::integer                                                     AS pop,
       a.median_hh_income::integer                                        AS median_hh_income,
       a.median_hh_income_moe::integer                                    AS median_hh_income_moe,
       a.median_home_value::integer                                       AS median_home_value,
       a.median_age::float8                                               AS median_age,
       round(100.0 * a.poverty_count / nullif(a.poverty_universe, 0), 1)::float8 AS poverty_pct,
       t.geom
FROM src_census.tract t
LEFT JOIN src_census.acs5_2024_tract a USING (geoid);

COMMENT ON VIEW pub.maine_overview__tracts IS 'maine-overview: census tracts with ACS 2020-2024 5-year estimates';
