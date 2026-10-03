-- Maine Habitat: Essential Habitats under Maine's Endangered Species Act (MDIFW).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__essential_habitats;
CREATE OR REPLACE VIEW pub.maine_habitat__essential_habitats AS
SELECT 'rt-' || id AS id, 'roseate tern' AS species, site, town, acres::float8 AS acres, ST_Force2D(geom)::geometry(MultiPolygon, 4326) AS geom FROM src_habitat.eh_roseate_tern
UNION ALL
SELECT 'pt-' || id, 'piping plover and least tern', site, NULL, acres::float8, ST_Force2D(geom)::geometry(MultiPolygon, 4326) AS geom FROM src_habitat.eh_piping_plover_least_tern;

COMMENT ON VIEW pub.maine_habitat__essential_habitats IS 'maine-habitat: essential habitats (MDIFW, Maine Endangered Species Act)';
