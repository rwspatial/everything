-- migrate:up
-- Remove the Hydrology Sketch placeholder project (Natural Earth lakes and rivers, the only tipg-geojson layer and the
-- example PostGIS function layer) and its data. The tipg-geojson source type is gone from the manifest contract;
-- function layers stay supported. Safe to run where none of it exists (fresh installs).
DROP FUNCTION IF EXISTS pub.hydrology_sketch__rivers_by_rank(int, int, int, int);
DROP VIEW IF EXISTS pub.hydrology_sketch__rivers;
DROP VIEW IF EXISTS pub.hydrology_sketch__lakes;
DROP TABLE IF EXISTS src_ne.lakes;
DROP TABLE IF EXISTS src_ne.rivers;
-- Registry: the project (its manifest versions and reports follow by cascade) and the two recipes with their outputs
-- and run history (coverages, parts and freshness checks follow by cascade).
DELETE FROM app.projects WHERE slug = 'hydrology-sketch';
DELETE FROM app.dataset_outputs WHERE recipe_name IN ('ne_lakes', 'ne_rivers') OR locator LIKE 'pub.hydrology\_sketch\_\_%';
DELETE FROM app.runs WHERE recipe_name IN ('ne_lakes', 'ne_rivers');
DELETE FROM app.jobs WHERE recipe_name IN ('ne_lakes', 'ne_rivers');
DELETE FROM app.recipes WHERE name IN ('ne_lakes', 'ne_rivers');

-- migrate:down
-- Not reversible here: restore projects/hydrology-sketch, db/seed/020_hydrology_sketch.sql and the ne_lakes/ne_rivers
-- recipes from git, then make import-recipe r=ne_lakes, r=ne_rivers, make seed and ./mapgen apply hydrology-sketch.
SELECT 1;
