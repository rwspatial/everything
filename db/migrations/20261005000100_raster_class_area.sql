-- migrate:up
-- Area of each class of a categorical raster (land cover, crops, ...) per Maine county, written by
-- `geoimport.py class-stats` after a raster recipe with `class_stats: true` builds its COG. Rasters are files
-- (data/cog), so this is the table charts read: projects publish labelled views of it (e.g. maine-landcover).
--
--   role       | rights here
--   loader     | replace a raster's rows
--   src_reader | read (core-api, tipg views, MCP)
CALL app.ensure_src_schema('src_raster');

CREATE TABLE src_raster.class_area (
    cog          text NOT NULL,              -- COG name, e.g. maine/nlcd_2025_landcover
    county_geoid text NOT NULL,              -- src_census.county.geoid
    value        integer NOT NULL,           -- the raster's class code
    pixels       bigint NOT NULL,
    acres        double precision NOT NULL,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cog, county_geoid, value)
);
GRANT SELECT, INSERT, DELETE ON src_raster.class_area TO loader;
GRANT SELECT ON src_raster.class_area TO src_reader;

-- migrate:down
DROP TABLE src_raster.class_area;
DROP SCHEMA src_raster;
