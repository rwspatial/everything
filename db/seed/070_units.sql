-- Units for the project builder (plan: project-builder §1.1; table app.units in migration 20261003000800).
-- One view per unit, pub.units__<id>, all with the same standard columns so the builder, the study-area
-- filter and (Stage 2) the analyses can treat every unit alike:
--   id integer, unit_key text, name text, county_geoid text, county_name text, town_geoid text, area_sqmi float8,
--   <attributes, float8>, geom geometry(MultiPolygon, 4326)
-- town_geoid is NULL for units that do not nest in towns (tract, block group, county, state).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
-- ACS values below zero are Census "not available" codes and become NULL.

-- ---- lookups: the town (county subdivision) each block and parcel lies in --------------------------------------
-- Blocks nest in county subdivisions; their internal point decides. Parcels use a point on their surface.
-- Rebuilt only when the source row counts change (parcels take about a minute), so `make seed` stays quick.
CREATE TABLE IF NOT EXISTS src_units.block_town (geoid20 text PRIMARY KEY, town_geoid text);
CREATE TABLE IF NOT EXISTS src_units.parcel_town (id integer PRIMARY KEY, town_geoid text, county_geoid text);
CREATE TABLE IF NOT EXISTS src_units.state (id integer PRIMARY KEY, geoid text, name text, aland float8,
                                            geom geometry(MultiPolygon, 4326));
GRANT SELECT ON ALL TABLES IN SCHEMA src_units TO src_reader;

DO $$
BEGIN
  IF (SELECT count(*) FROM src_units.block_town) <> (SELECT count(*) FROM src_census.block) THEN
    RAISE NOTICE 'units: rebuilding block -> town lookup';
    TRUNCATE src_units.block_town;
    INSERT INTO src_units.block_town
    SELECT b.geoid20, c.geoid
    FROM src_census.block b
    LEFT JOIN LATERAL (
      SELECT c.geoid FROM src_census.cousub c
      WHERE ST_Intersects(c.geom, ST_SetSRID(ST_MakePoint(b.intptlon20::float8, b.intptlat20::float8), 4326)) LIMIT 1
    ) c ON true;
  END IF;

  IF (SELECT count(*) FROM src_units.parcel_town)
     <> (SELECT count(*) FROM src_megis.parcels_organized) + (SELECT count(*) FROM src_megis.parcels_unorganized) THEN
    RAISE NOTICE 'units: rebuilding parcel -> town lookup';
    TRUNCATE src_units.parcel_town;
    CREATE TEMP TABLE cousub_parts ON COMMIT DROP AS
      SELECT geoid, ST_Subdivide(geom, 128) AS geom FROM src_census.cousub;
    CREATE INDEX ON cousub_parts USING gist (geom);
    ANALYZE cousub_parts;
    -- Parcel ids match pub.maine_lands__parcels: organized ids as is, unorganized ids + 10,000,000.
    INSERT INTO src_units.parcel_town
    SELECT p.id, c.geoid, left(c.geoid, 5)
    FROM (SELECT id, geom FROM src_megis.parcels_organized
          UNION ALL SELECT 10000000 + id, geom FROM src_megis.parcels_unorganized) p
    LEFT JOIN LATERAL (
      SELECT c.geoid FROM cousub_parts c WHERE ST_Intersects(c.geom, ST_PointOnSurface(p.geom)) LIMIT 1
    ) c ON true;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM src_units.state)
     OR (SELECT aland FROM src_units.state) <> (SELECT sum(aland) FROM src_census.county) THEN
    RAISE NOTICE 'units: rebuilding the state outline';
    TRUNCATE src_units.state;
    INSERT INTO src_units.state
    SELECT 1, '23', 'Maine', sum(aland)::float8, ST_Multi(ST_Union(geom))::geometry(MultiPolygon, 4326)
    FROM src_census.county;
  END IF;
END
$$;
ANALYZE src_units.block_town;
ANALYZE src_units.parcel_town;

-- ---- views -------------------------------------------------------------------------------------------------------
DROP VIEW IF EXISTS pub.units__state;
CREATE VIEW pub.units__state AS
SELECT s.id, s.geoid AS unit_key, s.name, NULL::text AS county_geoid, NULL::text AS county_name, NULL::text AS town_geoid,
       s.aland / 2589988.11 AS area_sqmi,
       sum((CASE WHEN a.pop >= 0 THEN a.pop::float8 END)) AS pop,
       sum((CASE WHEN a.pop >= 0 THEN a.pop::float8 END)) / (s.aland / 2589988.11) AS pop_density,
       s.geom
FROM src_units.state s CROSS JOIN src_census.acs5_2024_county a
GROUP BY s.id, s.geoid, s.name, s.aland, s.geom;

DROP VIEW IF EXISTS pub.units__county;
CREATE VIEW pub.units__county AS
SELECT c.id, c.geoid AS unit_key, c.namelsad AS name, c.geoid AS county_geoid, c.name AS county_name, NULL::text AS town_geoid,
       c.aland / 2589988.11 AS area_sqmi,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) AS pop,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) / nullif(c.aland / 2589988.11, 0) AS pop_density,
       (CASE WHEN a.median_hh_income >= 0 THEN a.median_hh_income::float8 END) AS median_hh_income,
       (CASE WHEN a.median_home_value >= 0 THEN a.median_home_value::float8 END) AS median_home_value,
       (CASE WHEN a.median_age >= 0 THEN a.median_age::float8 END) AS median_age,
       100 * (CASE WHEN a.poverty_count >= 0 THEN a.poverty_count::float8 END) / nullif((CASE WHEN a.poverty_universe >= 0 THEN a.poverty_universe::float8 END), 0) AS poverty_pct,
       c.geom
FROM src_census.county c LEFT JOIN src_census.acs5_2024_county a USING (geoid);

DROP VIEW IF EXISTS pub.units__town;
CREATE VIEW pub.units__town AS
SELECT t.id, t.geoid AS unit_key, t.namelsad AS name, left(t.geoid, 5) AS county_geoid, c.name AS county_name,
       t.geoid AS town_geoid,
       t.aland / 2589988.11 AS area_sqmi,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) AS pop,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) / nullif(t.aland / 2589988.11, 0) AS pop_density,
       (CASE WHEN a.median_hh_income >= 0 THEN a.median_hh_income::float8 END) AS median_hh_income,
       t.geom
FROM src_census.cousub t
LEFT JOIN src_census.acs5_2024_cousub a USING (geoid)
LEFT JOIN src_census.county c ON c.geoid = left(t.geoid, 5);

DROP VIEW IF EXISTS pub.units__tract;
CREATE VIEW pub.units__tract AS
SELECT t.id, t.geoid AS unit_key, t.namelsad || ', ' || c.name || ' County' AS name, left(t.geoid, 5) AS county_geoid,
       c.name AS county_name, NULL::text AS town_geoid,
       t.aland / 2589988.11 AS area_sqmi,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) AS pop,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) / nullif(t.aland / 2589988.11, 0) AS pop_density,
       (CASE WHEN a.median_hh_income >= 0 THEN a.median_hh_income::float8 END) AS median_hh_income,
       (CASE WHEN a.median_home_value >= 0 THEN a.median_home_value::float8 END) AS median_home_value,
       (CASE WHEN a.median_age >= 0 THEN a.median_age::float8 END) AS median_age,
       100 * (CASE WHEN a.poverty_count >= 0 THEN a.poverty_count::float8 END) / nullif((CASE WHEN a.poverty_universe >= 0 THEN a.poverty_universe::float8 END), 0) AS poverty_pct,
       t.geom
FROM src_census.tract t
LEFT JOIN src_census.acs5_2024_tract a USING (geoid)
LEFT JOIN src_census.county c ON c.geoid = left(t.geoid, 5);

DROP VIEW IF EXISTS pub.units__blockgroup;
CREATE VIEW pub.units__blockgroup AS
SELECT g.id, g.geoid AS unit_key,
       g.namelsad || ', Tract ' || ltrim(left(g.tractce, 4), '0') || coalesce(nullif('.' || right(g.tractce, 2), '.00'), '')
         || ', ' || c.name || ' County' AS name,
       left(g.geoid, 5) AS county_geoid, c.name AS county_name, NULL::text AS town_geoid,
       g.aland / 2589988.11 AS area_sqmi,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) AS pop,
       (CASE WHEN a.pop >= 0 THEN a.pop::float8 END) / nullif(g.aland / 2589988.11, 0) AS pop_density,
       (CASE WHEN a.median_hh_income >= 0 THEN a.median_hh_income::float8 END) AS median_hh_income,
       (CASE WHEN a.median_home_value >= 0 THEN a.median_home_value::float8 END) AS median_home_value,
       (CASE WHEN a.median_age >= 0 THEN a.median_age::float8 END) AS median_age,
       100 * ((CASE WHEN a.poverty_under_50pct >= 0 THEN a.poverty_under_50pct::float8 END) + (CASE WHEN a.poverty_50_to_99pct >= 0 THEN a.poverty_50_to_99pct::float8 END))
         / nullif((CASE WHEN a.poverty_universe >= 0 THEN a.poverty_universe::float8 END), 0) AS poverty_pct,
       g.geom
FROM src_census.blockgroup g
LEFT JOIN src_census.acs5_2024_blockgroup a USING (geoid)
LEFT JOIN src_census.county c ON c.geoid = left(g.geoid, 5);

DROP VIEW IF EXISTS pub.units__block;
CREATE VIEW pub.units__block AS
SELECT b.id, b.geoid20 AS unit_key, 'Block ' || b.blockce20 || ', ' || coalesce(t.name, c.name || ' County') AS name,
       left(b.geoid20, 5) AS county_geoid, c.name AS county_name, bt.town_geoid,
       b.aland20 / 2589988.11 AS area_sqmi,
       d.pop::float8 AS pop,
       d.pop::float8 / nullif(b.aland20 / 2589988.11, 0) AS pop_density,
       d.housing_units::float8 AS housing_units,
       100 * d.vacant_units::float8 / nullif(d.housing_units, 0)::float8 AS vacant_pct,
       b.geom
FROM src_census.block b
LEFT JOIN src_census.dec2020_block d ON d.geoid = b.geoid20
LEFT JOIN src_units.block_town bt ON bt.geoid20 = b.geoid20
LEFT JOIN src_census.cousub t ON t.geoid = bt.town_geoid
LEFT JOIN src_census.county c ON c.geoid = left(b.geoid20, 5);

-- Parcels: the geometry column is passed through unwrapped so tiPG's tile filter uses the GiST index
-- (see projects/maine-lands/sql/080_parcels.sql, which this mirrors with unit columns added).
DROP VIEW IF EXISTS pub.units__parcel;
CREATE VIEW pub.units__parcel AS
SELECT p.id, p.id::text AS unit_key,
       concat_ws(', ', p.address, 'map/lot ' || p.map_lot, t.name) AS name,
       pt.county_geoid, c.name AS county_name, pt.town_geoid,
       p.acres / 640 AS area_sqmi,
       p.acres,
       p.geom
FROM (
  SELECT id, nullif(regexp_replace(trim(map_bk_lot), '\s+', ' ', 'g'), '') AS map_lot,
         nullif(regexp_replace(regexp_replace(trim(prop_loc), '^0+(\d)', '\1'), '^0 ', ''), '') AS address,
         (shape__area / 4046.8564224)::float8 AS acres, geom
  FROM src_megis.parcels_organized
  UNION ALL
  SELECT 10000000 + id, nullif(regexp_replace(trim(coalesce(plan_lot, lot)), '\s+', ' ', 'g'), ''), NULL,
         coalesce(nullif(totacres, 0), ST_Area(geom::geography) / 4046.8564224)::float8, geom
  FROM src_megis.parcels_unorganized
) p
LEFT JOIN src_units.parcel_town pt ON pt.id = p.id
LEFT JOIN src_census.cousub t ON t.geoid = pt.town_geoid
LEFT JOIN src_census.county c ON c.geoid = pt.county_geoid;

COMMENT ON VIEW pub.units__state IS 'units: the state (Maine), with ACS 2024 population summed from counties';
COMMENT ON VIEW pub.units__county IS 'units: counties with ACS 2024 5-year estimates';
COMMENT ON VIEW pub.units__town IS 'units: towns, cities, plantations and townships (Census county subdivisions) with ACS 2024';
COMMENT ON VIEW pub.units__tract IS 'units: census tracts with ACS 2024 5-year estimates';
COMMENT ON VIEW pub.units__blockgroup IS 'units: census block groups with ACS 2024 5-year estimates';
COMMENT ON VIEW pub.units__block IS 'units: census blocks with Decennial 2020 counts';
COMMENT ON VIEW pub.units__parcel IS 'units: tax parcels (MEGIS), organized towns and Unorganized Territory';

-- ---- catalog -------------------------------------------------------------------------------------------------------
WITH a AS (
  SELECT * FROM (VALUES
    ('pop',               'Population',                     'count',    'ACS 2024 5-year'),
    ('pop_density',       'People per square mile',         'density',  'ACS 2024 5-year'),
    ('median_hh_income',  'Median household income',        'currency', 'ACS 2024 5-year'),
    ('median_home_value', 'Median home value',               'currency', 'ACS 2024 5-year'),
    ('median_age',        'Median age',                      'years',    'ACS 2024 5-year'),
    ('poverty_pct',       'Below the poverty line (%)',      'percent',  'ACS 2024 5-year'),
    ('area_sqmi',         'Land area (sq mi)',               'area',     'Census TIGER/Line')
  ) v(field, title, format, source)
), attrs AS (
  SELECT jsonb_agg(jsonb_build_object('field', field, 'title', title, 'format', format, 'source', source)
                   ORDER BY array_position(ARRAY['pop','pop_density','median_hh_income','median_home_value',
                                                 'median_age','poverty_pct','area_sqmi'], field))
           FILTER (WHERE field = ANY (fields)) AS j, unit
  FROM a CROSS JOIN (VALUES
    ('state',      ARRAY['pop','pop_density','area_sqmi']),
    ('county',     ARRAY['pop','pop_density','median_hh_income','median_home_value','median_age','poverty_pct','area_sqmi']),
    ('town',       ARRAY['pop','pop_density','median_hh_income','area_sqmi']),
    ('tract',      ARRAY['pop','pop_density','median_hh_income','median_home_value','median_age','poverty_pct','area_sqmi']),
    ('blockgroup', ARRAY['pop','pop_density','median_hh_income','median_home_value','median_age','poverty_pct','area_sqmi'])
  ) u(unit, fields)
  GROUP BY unit
)
INSERT INTO app.units AS u (id, title, plural, description, collection, position, study_area,
                            max_units_without_study_area, minzoom, unit_count, attributes, attribution)
SELECT v.id, v.title, v.plural, v.description, 'pub.units__' || v.id, v.position, v.study_area::jsonb, v.max_units,
       v.minzoom, v.unit_count, coalesce(v.attributes, attrs.j), v.attribution
FROM (VALUES
  ('state', 'State', 'States', 'Maine as a whole. Useful for statewide summaries and reports.', 70, '[]', NULL::int, 0,
   (SELECT count(*) FROM src_units.state), NULL::jsonb, 'U.S. Census Bureau: TIGER/Line 2024, ACS 2024 5-year'),
  ('county', 'County', 'Counties', 'The 16 counties, with ACS 2024 5-year estimates.', 60,
   '[{"by": "county", "field": "county_geoid"}]', NULL, 0, (SELECT count(*) FROM src_census.county), NULL,
   'U.S. Census Bureau: TIGER/Line 2024, ACS 2024 5-year'),
  ('town', 'Town', 'Towns', 'Cities, towns, plantations and unorganized townships (Census county subdivisions), with ACS 2024 5-year estimates.', 50,
   '[{"by": "county", "field": "county_geoid"}, {"by": "town", "field": "town_geoid"}]', NULL, 0,
   (SELECT count(*) FROM src_census.cousub), NULL, 'U.S. Census Bureau: TIGER/Line 2024, ACS 2024 5-year'),
  ('tract', 'Census tract', 'Census tracts', 'Census tracts (about 4,000 people each), with ACS 2024 5-year estimates.', 40,
   '[{"by": "county", "field": "county_geoid"}]', NULL, 0, (SELECT count(*) FROM src_census.tract), NULL,
   'U.S. Census Bureau: TIGER/Line 2024, ACS 2024 5-year'),
  ('blockgroup', 'Block group', 'Block groups', 'Census block groups (about 1,000 people each), the smallest unit with ACS estimates.', 30,
   '[{"by": "county", "field": "county_geoid"}]', NULL, 6, (SELECT count(*) FROM src_census.blockgroup), NULL,
   'U.S. Census Bureau: TIGER/Line 2024, ACS 2024 5-year'),
  ('block', 'Census block', 'Census blocks', 'Census blocks, with Decennial 2020 population and housing counts.', 20,
   '[{"by": "county", "field": "county_geoid"}, {"by": "town", "field": "town_geoid"}]', 5000, 10,
   (SELECT count(*) FROM src_census.block),
   '[{"field": "pop", "title": "Population (2020)", "format": "count", "source": "Decennial Census 2020"},
     {"field": "pop_density", "title": "People per square mile (2020)", "format": "density", "source": "Decennial Census 2020"},
     {"field": "housing_units", "title": "Housing units (2020)", "format": "count", "source": "Decennial Census 2020"},
     {"field": "vacant_pct", "title": "Vacant housing units (%)", "format": "percent", "source": "Decennial Census 2020"},
     {"field": "area_sqmi", "title": "Land area (sq mi)", "format": "area", "source": "Census TIGER/Line"}]'::jsonb,
   'U.S. Census Bureau: TIGER/Line 2020, Decennial Census 2020'),
  ('parcel', 'Parcel', 'Parcels', 'Tax parcels: municipal tax maps in organized towns, Maine Revenue Services plans in the Unorganized Territory.', 10,
   '[{"by": "county", "field": "county_geoid"}, {"by": "town", "field": "town_geoid"}]', 50000, 13,
   (SELECT count(*) FROM src_units.parcel_town),
   '[{"field": "acres", "title": "Acres", "format": "acres", "source": "MEGIS parcels"}]'::jsonb,
   'Maine GeoLibrary (MEGIS) parcels; Maine Revenue Services (Unorganized Territory)')
) v(id, title, plural, description, position, study_area, max_units, minzoom, unit_count, attributes, attribution)
LEFT JOIN attrs ON attrs.unit = v.id
ON CONFLICT (id) DO UPDATE SET
  title = EXCLUDED.title, plural = EXCLUDED.plural, description = EXCLUDED.description,
  collection = EXCLUDED.collection, position = EXCLUDED.position, study_area = EXCLUDED.study_area,
  max_units_without_study_area = EXCLUDED.max_units_without_study_area, minzoom = EXCLUDED.minzoom,
  unit_count = EXCLUDED.unit_count, attributes = EXCLUDED.attributes, attribution = EXCLUDED.attribution,
  updated_at = now();
