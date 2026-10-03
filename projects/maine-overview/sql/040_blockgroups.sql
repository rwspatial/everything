-- Maine Overview: block groups -> pub.maine_overview__blockgroups (TIGER/Line 2024 joined to ACS 2020-2024 on GEOID).
-- Block groups are the smallest ACS areas; their estimates carry wide margins of error. Poverty: C17002, below 1.00.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_overview__blockgroups;
CREATE OR REPLACE VIEW pub.maine_overview__blockgroups AS
SELECT b.id,
       b.geoid,
       b.namelsad || ', tract ' || ltrim(b.tractce, '0')                  AS name,
       split_part(a.name, '; ', 3)                                        AS county,
       a.pop::integer                                                     AS pop,
       a.median_hh_income::integer                                        AS median_hh_income,
       a.median_hh_income_moe::integer                                    AS median_hh_income_moe,
       a.median_home_value::integer                                       AS median_home_value,
       a.median_age::float8                                               AS median_age,
       round(100.0 * (a.poverty_under_50pct + a.poverty_50_to_99pct) / nullif(a.poverty_universe, 0), 1)::float8 AS poverty_pct,
       b.geom
FROM src_census.blockgroup b
LEFT JOIN src_census.acs5_2024_blockgroup a USING (geoid);

COMMENT ON VIEW pub.maine_overview__blockgroups IS 'maine-overview: census block groups with ACS 2020-2024 5-year estimates';
