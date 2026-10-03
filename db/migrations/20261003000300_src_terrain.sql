-- migrate:up
-- Terrain products derived from the 3DEP elevation model (contour lines; the rasters live in data/cog/maine/).
CALL app.ensure_src_schema('src_terrain');

-- migrate:down
DROP SCHEMA IF EXISTS src_terrain CASCADE;
