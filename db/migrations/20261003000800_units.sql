-- migrate:up
-- Units for the project builder (plan: project-builder §1.1). A project is built around one unit (parcel, block,
-- block group, tract, town, county, state) and a study area. db/seed/070_units.sql publishes one view per unit,
-- pub.units__<id>, with the same standard columns, and upserts its row here, so the catalog and the view it
-- describes are always written together.
--
--   role      | used by                              | rights here
--   app_rw    | core-api (/api/admin/units, builder) | read
--   admin_api | core-api (dashboard)                 | read

-- Precomputed lookups (which town and county each block and parcel lies in). Written by the seed, never served.
CALL app.ensure_src_schema('src_units');

CREATE TABLE app.units (
    id           text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9_]*$'),
    title        text NOT NULL,
    plural       text NOT NULL,
    description  text NOT NULL,
    collection   text NOT NULL CHECK (collection ~ '^pub\.units__[a-z0-9_]+$'),
    position     integer NOT NULL,
    -- How a study area narrows this unit: [{"by": "county", "field": "county_geoid"}, {"by": "town", ...}].
    study_area   jsonb NOT NULL DEFAULT '[]',
    -- Above this many units a study area is required (parcels, blocks); NULL = never required.
    max_units_without_study_area integer,
    minzoom      integer NOT NULL DEFAULT 0,
    unit_count   bigint NOT NULL DEFAULT 0,
    -- Mappable columns of the view: [{"field", "title", "format": count|currency|percent|density|years|acres, "source"}].
    attributes   jsonb NOT NULL DEFAULT '[]',
    attribution  text NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT ON app.units TO app_rw, admin_api;

-- migrate:down
DROP TABLE IF EXISTS app.units;
DROP SCHEMA IF EXISTS src_units CASCADE;
