-- Placeholder project: world-overview (status: draft)
-- Requires recipes: ne_countries, ne_populated_places  (make import-all)
-- Also requires recipe ne_admin1 (states and provinces).
--
-- Seeds are idempotent (CREATE OR REPLACE). If you change a view's columns,
-- DROP the view first: CREATE OR REPLACE VIEW cannot remove or retype columns.

CREATE OR REPLACE VIEW pub.world_overview__countries AS
SELECT id,
       name,
       name_long,
       iso_a3,
       continent,
       subregion,
       pop_est::bigint AS pop_est,
       gdp_md::bigint  AS gdp_md,
       income_grp,
       geom
FROM src_ne.countries;
COMMENT ON VIEW pub.world_overview__countries IS 'world-overview: countries (Natural Earth 1:110m)';

CREATE OR REPLACE VIEW pub.world_overview__places AS
SELECT id,
       name,
       adm0name,
       featurecla,
       pop_max::bigint AS pop_max,
       geom
FROM src_ne.populated_places;
COMMENT ON VIEW pub.world_overview__places IS 'world-overview: populated places (Natural Earth 1:110m, simple)';

CREATE OR REPLACE VIEW pub.world_overview__admin1 AS
SELECT id, name, admin AS country, type_en AS type, iso_3166_2 AS code, geom
FROM src_ne.admin1;
COMMENT ON VIEW pub.world_overview__admin1 IS 'world-overview: states and provinces (Natural Earth 1:50m)';
