-- Placeholder project: hydrology-sketch (status: stub)
-- Requires recipes: ne_rivers, ne_lakes  (make import-all)
-- Deliberately missing: watersheds, gauges (todo layers; would load into src_hydro).

CREATE OR REPLACE VIEW pub.hydrology_sketch__rivers AS
SELECT id,
       name,
       scalerank::int AS scalerank,
       featurecla,
       min_zoom,
       geom
FROM src_ne.rivers;
COMMENT ON VIEW pub.hydrology_sketch__rivers IS 'hydrology-sketch: rivers and lake centerlines (Natural Earth 1:10m)';

CREATE OR REPLACE VIEW pub.hydrology_sketch__lakes AS
SELECT id,
       name,
       scalerank::int AS scalerank,
       featurecla,
       geom
FROM src_ne.lakes;
COMMENT ON VIEW pub.hydrology_sketch__lakes IS 'hydrology-sketch: lakes (Natural Earth 1:10m), small enough for GeoJSON';

-- Function collection (parametrized layer). tiPG fills z/x/y from the tile path;
-- max_scalerank comes from the query string: .../tiles/WebMercatorQuad/{z}/{x}/{y}?max_scalerank=4
-- SECURITY DEFINER: tipg_ro may not read src_ne directly, so the function runs as its owner.
CREATE OR REPLACE FUNCTION pub.hydrology_sketch__rivers_by_rank(
  IN  z int,
  IN  x int,
  IN  y int,
  IN  max_scalerank int DEFAULT 6,
  OUT id int,
  OUT name text,
  OUT scalerank int,
  OUT geom geometry
) RETURNS SETOF record
LANGUAGE sql STABLE PARALLEL SAFE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT r.id, r.name::text, r.scalerank::int, r.geom
  FROM src_ne.rivers AS r
  WHERE r.scalerank <= max_scalerank
    AND r.geom && ST_Transform(ST_TileEnvelope(z, x, y), 4326)
$$;
COMMENT ON FUNCTION pub.hydrology_sketch__rivers_by_rank IS 'hydrology-sketch: rivers filtered by max_scalerank (0 = major only, 10+ = all)';
