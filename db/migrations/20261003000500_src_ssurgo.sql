-- migrate:up
-- USDA-NRCS SSURGO soils for Maine: map-unit polygons (Web Soil Survey) and map-unit attributes (Soil Data Access).
CALL app.ensure_src_schema('src_ssurgo');

-- migrate:down
DROP SCHEMA IF EXISTS src_ssurgo CASCADE;
