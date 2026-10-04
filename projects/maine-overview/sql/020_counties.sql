-- Maine Overview: demographics by county -> pub.maine_overview__counties (TIGER/Line 2024 joined to ACS 2020-2024 on GEOID).
-- Columns: population and age (median age, % under 18, % 65 and over), median household income, poverty rate,
-- % of adults 25+ with a bachelor's degree or higher, % people of color (everyone but non-Hispanic white), % Hispanic
-- or Latino, and housing (units, median home value, % owner-occupied, % seasonal: vacant homes held for seasonal,
-- recreational or occasional use). Shares are NULL where the Census Bureau suppresses an estimate or the base is 0.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_overview__counties;
CREATE VIEW pub.maine_overview__counties AS
SELECT c.id,
       c.geoid,
       c.namelsad                                                         AS name,
       p.pop::integer                                                     AS pop,
       p.median_age::float8                                               AS median_age,
       round(100.0 * (p.under_18) / nullif(p.pop, 0), 1)::float8 AS pct_under_18,
       round(100.0 * (p.m65_66 + p.m67_69 + p.m70_74 + p.m75_79 + p.m80_84 + p.m85_plus + p.f65_66 + p.f67_69 + p.f70_74 + p.f75_79 + p.f80_84 + p.f85_plus) / nullif(p.pop, 0), 1)::float8 AS pct_65_plus,
       a.median_hh_income::integer                                        AS median_hh_income,
       a.median_hh_income_moe::integer                                    AS median_hh_income_moe,
       round(100.0 * (p.poverty_count) / nullif(p.poverty_universe, 0), 1)::float8 AS poverty_pct,
       round(100.0 * (p.bachelors + p.masters + p.professional + p.doctorate) / nullif(p.edu_universe, 0), 1)::float8 AS pct_bachelors,
       round(100.0 * (p.race_universe - p.white_nh) / nullif(p.race_universe, 0), 1)::float8 AS pct_people_of_color,
       round(100.0 * (p.hispanic) / nullif(p.race_universe, 0), 1)::float8 AS pct_hispanic,
       p.housing_units::integer                                           AS housing_units,
       p.median_home_value::integer                                       AS median_home_value,
       round(100.0 * (p.owner_occupied) / nullif(p.occupied_units, 0), 1)::float8 AS pct_owner_occupied,
       round(100.0 * (p.seasonal_units) / nullif(p.housing_units, 0), 1)::float8 AS pct_seasonal,
       c.geom
FROM src_census.county c
LEFT JOIN src_census.acs5_2024_county a USING (geoid)
LEFT JOIN src_census.acs5_2024_profile_county p USING (geoid);

COMMENT ON VIEW pub.maine_overview__counties IS 'maine-overview: demographics by county (ACS 2020-2024 5-year)';
