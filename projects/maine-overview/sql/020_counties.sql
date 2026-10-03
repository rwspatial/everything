-- Maine Overview: counties -> pub.maine_overview__counties (TIGER/Line 2024 joined to ACS 2020-2024 on GEOID).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_overview__counties;
CREATE OR REPLACE VIEW pub.maine_overview__counties AS
SELECT c.id,
       c.geoid,
       c.namelsad                                                         AS name,
       a.pop::integer                                                     AS pop,
       a.median_hh_income::integer                                        AS median_hh_income,
       a.median_hh_income_moe::integer                                    AS median_hh_income_moe,
       a.median_home_value::integer                                       AS median_home_value,
       a.median_age::float8                                               AS median_age,
       round(100.0 * a.poverty_count / nullif(a.poverty_universe, 0), 1)::float8 AS poverty_pct,
       c.geom
FROM src_census.county c
LEFT JOIN src_census.acs5_2024_county a USING (geoid);

COMMENT ON VIEW pub.maine_overview__counties IS 'maine-overview: counties with ACS 2020-2024 5-year estimates';
