-- migrate:up
-- Manual settlement edits (plan: classification §1). An admin draws polygons in /admin/methods/settlements/edit;
-- each has one action, applied on top of the computed settlements (projects/maine-places/sql/030_settlements.sql)
-- by src_units.apply_settlement_edits(), so edits survive method changes and rebuilds:
--   replace  the drawn outline becomes the settlement; computed shapes are cut away inside it
--   add      a settlement where the method found none; computed shapes it overlaps merge into it
--   remove   computed settlements inside it are removed (not a settlement)
-- Optional: a name (instead of "named after the town") and a size class (the classification override).
--
--   role   | used by  | rights here
--   app_rw | core-api | read and write edits (admin endpoints only)
CREATE TABLE app.settlement_edits (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    action      text NOT NULL CHECK (action IN ('replace', 'add', 'remove')),
    name        text CHECK (name IS NULL OR length(name) BETWEEN 1 AND 120),
    size_class  text CHECK (size_class IS NULL OR size_class IN ('City or large town', 'Town centre', 'Village', 'Hamlet')),
    note        text CHECK (note IS NULL OR length(note) <= 1000),
    geom        geometry(MultiPolygon, 4326) NOT NULL CHECK (ST_IsValid(geom) AND NOT ST_IsEmpty(geom)),
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX settlement_edits_geom_idx ON app.settlement_edits USING gist (geom);
GRANT SELECT, INSERT, UPDATE, DELETE ON app.settlement_edits TO app_rw;

-- migrate:down
DROP TABLE app.settlement_edits;
