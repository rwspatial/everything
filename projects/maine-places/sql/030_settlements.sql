-- Maine Places: settlements -> pub.maine_places__settlements (outlines, z5-12; footprints take over from z13) and
-- pub.maine_places__density_grid (the 100 m grid they are classified from).
-- Method v4 (docs/methods/settlements.json): the Degree of Urbanisation (EU/OECD/FAO/UN-Habitat/ILO/World Bank, UN
-- Statistical Commission 2020) adapted to building footprints, since Maine has no population grid fine enough for
-- villages:
--   1. Grid: every footprint is counted in the 100 m cell (EPSG:26919) holding a point on its surface.
--   2. Density: buildings per hectare and footprint cover over each cell's 3x3 neighbourhood (300 m), so one house or
--      one empty lot does not decide a cell.
--   3. Cell classes: dense (>= 6 buildings/ha or >= 15 % cover), semi-dense (>= 2.5/ha or >= 6 %), low density
--      (>= 1/ha), very low density (the rest). Cover lets a downtown or mill district of few large buildings count.
--   4. Clusters: dense and semi-dense cells connected through neighbours (8 directions, plus a one-cell gap for a
--      river or highway) with >= 50 buildings are settlements: City (>= 2,500 buildings), Suburb (500-2,499 with
--      under 25 % of buildings in dense cells, within 15 km of a city), Town (the other 500-2,499), Village (50-499).
--   5. Outline: a cluster's own footprints closed into a shape (buffer 45 m, then -35 m), so edges follow buildings,
--      not grid squares. Low-density ribbons along roads stay outside instead of stretching the town.
--   6. The rest: buildings outside those clusters, clustered wall to wall (DBSCAN 45 m, 4 neighbours, >= 10 buildings)
--      as in v3, cut away where they overlap a settlement: Roadside strip when long and thin (oriented-rectangle
--      length/width >= 4 or Polsby-Popper < 0.12), else Hamlet (Village from 50 buildings).
--   7. Holes under max(10 acres, 3 % of the settlement) filled, simplified to 5 m, named after a town (the town holding
--      most of a City/Town/Suburb, else the town containing a point on its surface).
-- Built into src_units.settlements + src_units.settlement_cells, rebuilt only when the building count or the method
-- version changes (about six minutes), so `make seed` and `./mapgen apply maine-places` stay quick. To force a rebuild:
-- TRUNCATE src_units.settlements_meta.
CREATE TABLE IF NOT EXISTS src_units.settlements (
  id integer PRIMARY KEY, town_geoid text, buildings integer, footprint_acres float8,
  geom geometry(MultiPolygon, 4326));
ALTER TABLE src_units.settlements ADD COLUMN IF NOT EXISTS settlement_class text;
ALTER TABLE src_units.settlements ADD COLUMN IF NOT EXISTS core_share float8;
CREATE INDEX IF NOT EXISTS settlements_geom_idx ON src_units.settlements USING gist (geom);
CREATE TABLE IF NOT EXISTS src_units.settlements_meta (source_rows bigint, built_at timestamptz);
ALTER TABLE src_units.settlements_meta ADD COLUMN IF NOT EXISTS method integer;
CREATE TABLE IF NOT EXISTS src_units.settlement_cells (
  id integer PRIMARY KEY, i integer, j integer, buildings integer, density float8, cover float8, cell_class text,
  geom geometry(Polygon, 4326));
CREATE INDEX IF NOT EXISTS settlement_cells_geom_idx ON src_units.settlement_cells USING gist (geom);
GRANT SELECT ON src_units.settlements, src_units.settlements_meta, src_units.settlement_cells TO src_reader;

-- Fills the interior rings (holes) of a polygon smaller than min_m2 (same units as the geometry, here m2 in
-- EPSG:26919); larger holes are kept.
CREATE OR REPLACE FUNCTION src_units.fill_small_holes(g geometry, min_m2 float8) RETURNS geometry
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT ST_Collect(ST_MakePolygon(ST_ExteriorRing(p.geom),
           ARRAY(SELECT ST_ExteriorRing(h.geom) FROM ST_DumpRings(p.geom) h
                 WHERE h.path[1] > 0 AND ST_Area(h.geom) >= min_m2)))
  FROM ST_Dump(g) p
$$;

-- The class of a settlement drawn by hand without one (manual edits): by building count, as for computed clusters.
CREATE OR REPLACE FUNCTION src_units.settlement_class_for(buildings integer) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN buildings >= 2500 THEN 'City' WHEN buildings >= 500 THEN 'Town'
              WHEN buildings >= 50 THEN 'Village' ELSE 'Hamlet' END
$$;

DO $$
DECLARE
  src_rows bigint := (SELECT count(*) FROM src_overture.buildings);
  method_version CONSTANT integer := 4;  -- bump when the method below changes, to rebuild on the next apply
  p_cell CONSTANT float8 := 100;         -- grid cell (m)
  p_dense_ha CONSTANT float8 := 6;       -- buildings per hectare over the 3x3 neighbourhood
  p_dense_cover CONSTANT float8 := 0.15; -- or footprint cover
  p_semi_ha CONSTANT float8 := 2.5;
  p_semi_cover CONSTANT float8 := 0.06;
  p_low_ha CONSTANT float8 := 1;
  p_link CONSTANT float8 := 225;         -- cell centres within 225 m connect: 8 neighbours plus a one-cell gap
  p_min_cluster CONSTANT integer := 50;  -- buildings in a dense/semi-dense cluster to make a settlement
  p_suburb_m CONSTANT float8 := 15000;   -- a weak-core town within this distance of a city is a suburb
BEGIN
  IF EXISTS (SELECT 1 FROM src_units.settlements_meta WHERE source_rows = src_rows AND method = method_version) THEN
    RETURN;
  END IF;
  RAISE NOTICE 'settlements: classifying % buildings (method %)', src_rows, method_version;

  -- 1. Footprints in metres, each in the 100 m cell holding a point on its surface.
  CREATE TEMP TABLE fp ON COMMIT DROP AS
    SELECT b.g, b.m2, floor(ST_X(p.c) / p_cell)::int AS i, floor(ST_Y(p.c) / p_cell)::int AS j
    FROM (SELECT ST_Transform(geom, 26919) AS g, ST_Area(geom::geography) AS m2 FROM src_overture.buildings) b
    CROSS JOIN LATERAL (SELECT ST_PointOnSurface(b.g) AS c) p;
  CREATE INDEX ON fp (i, j);
  CREATE TEMP TABLE gc ON COMMIT DROP AS SELECT i, j, count(*)::int AS n, sum(m2) AS cov FROM fp GROUP BY i, j;
  CREATE INDEX ON gc (i, j);

  -- 2-3. Density over the 3x3 neighbourhood, and the cell class.
  CREATE TEMP TABLE gw ON COMMIT DROP AS
    SELECT c.i, c.j, c.n, sum(x.n) / (9 * p_cell * p_cell / 10000) AS dens, sum(x.cov) / (9 * p_cell * p_cell) AS covr
    FROM gc c JOIN gc x ON x.i BETWEEN c.i - 1 AND c.i + 1 AND x.j BETWEEN c.j - 1 AND c.j + 1
    GROUP BY c.i, c.j, c.n;
  ALTER TABLE gw ADD COLUMN cls text;
  UPDATE gw SET cls = CASE WHEN dens >= p_dense_ha OR covr >= p_dense_cover THEN 'Dense'
                           WHEN dens >= p_semi_ha OR covr >= p_semi_cover THEN 'Semi-dense'
                           WHEN dens >= p_low_ha THEN 'Low density'
                           ELSE 'Very low density' END;

  -- 4. Connected dense and semi-dense cells; clusters of 50+ buildings are settlements.
  CREATE TEMP TABLE gk ON COMMIT DROP AS
    SELECT i, j, n, cls, ST_ClusterDBSCAN(ST_MakePoint((i + 0.5) * p_cell, (j + 0.5) * p_cell), p_link, 1) OVER () AS kid
    FROM gw WHERE cls IN ('Dense', 'Semi-dense');
  CREATE TEMP TABLE gks ON COMMIT DROP AS
    SELECT kid, sum(n)::int AS n, coalesce(sum(n) FILTER (WHERE cls = 'Dense'), 0)::float8 / sum(n) AS core
    FROM gk GROUP BY kid HAVING sum(n) >= p_min_cluster;
  DELETE FROM gk WHERE kid NOT IN (SELECT kid FROM gks);
  CREATE INDEX ON gk (i, j);

  -- 5. Each settlement's own footprints closed into its outline.
  CREATE TEMP TABLE st ON COMMIT DROP AS
    SELECT count(*)::int AS n, sum(f.m2) AS m2, s.core,
           CASE WHEN s.n >= 2500 THEN 'City' WHEN s.n >= 500 AND s.core >= 0.25 THEN 'Town'
                WHEN s.n >= 500 THEN 'Suburb' ELSE 'Village' END AS cls,
           ST_Buffer(ST_Buffer(ST_Collect(f.g), 45, 4), -35, 4) AS g
    FROM fp f JOIN gk k USING (i, j) JOIN gks s USING (kid)
    GROUP BY k.kid, s.n, s.core;
  CREATE INDEX ON st USING gist (g);
  -- A suburb is beside a city: a weak core far from one is a rural service town (Ellsworth, Dover-Foxcroft).
  UPDATE st SET cls = 'Town'
  WHERE cls = 'Suburb' AND NOT EXISTS (SELECT 1 FROM st c WHERE c.cls = 'City' AND ST_DWithin(c.g, st.g, p_suburb_m));

  -- 6. The rest: wall-to-wall clusters of 10+ buildings outside the settlements, cut where they overlap one.
  CREATE TEMP TABLE lo ON COMMIT DROP AS
    SELECT count(*)::int AS n, sum(m2) AS m2, ST_Buffer(ST_Buffer(ST_Collect(g), 45, 4), -35, 4) AS g
    FROM (SELECT f.g, f.m2, ST_ClusterDBSCAN(f.g, 45, 4) OVER () AS cid
          FROM fp f WHERE NOT EXISTS (SELECT 1 FROM gk k WHERE k.i = f.i AND k.j = f.j)) x
    WHERE cid IS NOT NULL GROUP BY cid HAVING count(*) >= 10;
  UPDATE lo SET g = ST_CollectionExtract(ST_Difference(lo.g, (
      SELECT ST_Union(st.g) FROM st WHERE st.g && lo.g AND ST_Intersects(st.g, lo.g))), 3)
  WHERE EXISTS (SELECT 1 FROM st WHERE st.g && lo.g AND ST_Intersects(st.g, lo.g));
  DELETE FROM lo WHERE g IS NULL OR ST_IsEmpty(g) OR ST_Area(g) < 4046.8564224;
  INSERT INTO st (n, m2, core, cls, g)
  SELECT n, m2, 0,
         CASE WHEN e.elong >= 4 OR 4 * pi() * ST_Area(lo.g) / nullif(ST_Perimeter(lo.g) ^ 2, 0) < 0.12 THEN 'Roadside strip'
              WHEN n >= 50 THEN 'Village' ELSE 'Hamlet' END,
         lo.g
  FROM lo CROSS JOIN LATERAL (
    SELECT greatest(a, b) / nullif(least(a, b), 0) AS elong
    FROM (SELECT ST_Distance(ST_PointN(r, 1), ST_PointN(r, 2)) AS a, ST_Distance(ST_PointN(r, 2), ST_PointN(r, 3)) AS b
          FROM (SELECT ST_ExteriorRing(ST_OrientedEnvelope(lo.g)) AS r) q) z) e;

  -- 7. Fill small holes, simplify, name.
  TRUNCATE src_units.settlements;
  INSERT INTO src_units.settlements (id, town_geoid, buildings, footprint_acres, settlement_class, core_share, geom)
  SELECT row_number() OVER (ORDER BY n DESC)::int, NULL, n, m2 / 4046.8564224, cls, core,
         ST_Multi(ST_CollectionExtract(ST_Transform(ST_SimplifyPreserveTopology(
           src_units.fill_small_holes(g, greatest(10 * 4046.8564224, 0.03 * ST_Area(g))), 5), 4326), 3))
  FROM st WHERE g IS NOT NULL AND NOT ST_IsEmpty(g);
  UPDATE src_units.settlements s SET town_geoid = c.geoid
  FROM src_census.cousub c WHERE ST_Intersects(c.geom, ST_PointOnSurface(s.geom));
  -- A city or town spanning two towns (Lewiston-Auburn) is named after the one holding most of it.
  UPDATE src_units.settlements s SET town_geoid = (
      SELECT c.geoid FROM src_census.cousub c WHERE c.geom && s.geom AND ST_Intersects(c.geom, s.geom)
      ORDER BY ST_Area(ST_Intersection(c.geom, s.geom)) DESC LIMIT 1)
  WHERE s.settlement_class IN ('City', 'Town', 'Suburb');

  TRUNCATE src_units.settlement_cells;
  INSERT INTO src_units.settlement_cells (id, i, j, buildings, density, cover, cell_class, geom)
  SELECT row_number() OVER (ORDER BY i, j)::int, i, j, n, dens, covr, cls,
         ST_Transform(ST_MakeEnvelope(i * p_cell, j * p_cell, (i + 1) * p_cell, (j + 1) * p_cell, 26919), 4326)
  FROM gw WHERE cls <> 'Very low density';

  DELETE FROM src_units.settlements_meta;
  INSERT INTO src_units.settlements_meta (source_rows, built_at, method) VALUES (src_rows, now(), method_version);
END
$$;
ANALYZE src_units.settlements;
ANALYZE src_units.settlement_cells;

-- Manual edits (app.settlement_edits, drawn in /admin/methods/settlements/edit) applied on top of the computed
-- settlements into src_units.settlements_final, which the map reads. Applying takes seconds (no re-clustering), so
-- core-api calls it after every edit; it is SECURITY DEFINER because core-api cannot write src_units.
--   remove   computed settlements are cut away inside the polygon
--   replace  cut away likewise, then the drawn outline (exact, as drawn) becomes a settlement
--   add      the drawn outline plus every computed settlement it overlaps, as one settlement
-- What is left of a partly cut settlement stays a settlement (keeping its class) when it is at least 1 acre; edited
-- settlements get their building count and footprint recounted, and a name or class from the edit when one was given
-- (else the class from the building count, src_units.settlement_class_for).
DROP VIEW IF EXISTS pub.maine_places__settlements;
DROP TABLE IF EXISTS src_units.settlements_final;
CREATE TABLE src_units.settlements_final (
  id integer PRIMARY KEY, town_geoid text, buildings integer, footprint_acres float8, settlement_class text,
  core_share float8, source text NOT NULL, edit_id bigint, name text, geom geometry(MultiPolygon, 4326));
CREATE INDEX settlements_final_geom_idx ON src_units.settlements_final USING gist (geom);
GRANT SELECT ON src_units.settlements_final TO src_reader;

CREATE OR REPLACE FUNCTION src_units.apply_settlement_edits() RETURNS json
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  acre CONSTANT float8 := 4046.8564224;
  cut geometry;
  result json;
BEGIN
  DROP TABLE IF EXISTS se_out;
  CREATE TEMP TABLE se_out (g geometry, buildings integer, footprint_acres float8, town_geoid text,
                            settlement_class text, core_share float8, source text, edit_id bigint, name text);
  SELECT ST_Union(geom) INTO cut FROM app.settlement_edits WHERE action IN ('replace', 'remove');

  -- Computed settlements: untouched ones as they are; partly cut ones keep their parts of 1 acre or more and their
  -- class (recounted below); those an "add" absorbs are left to that add.
  INSERT INTO se_out (g, buildings, footprint_acres, town_geoid, settlement_class, core_share, source)
  SELECT CASE WHEN touched THEN p.g ELSE s.geom END,
         CASE WHEN touched THEN NULL ELSE s.buildings END,
         CASE WHEN touched THEN NULL ELSE s.footprint_acres END,
         CASE WHEN touched THEN NULL ELSE s.town_geoid END,
         s.settlement_class, s.core_share,
         CASE WHEN touched THEN 'edited' ELSE 'computed' END
  FROM src_units.settlements s
  CROSS JOIN LATERAL (SELECT cut IS NOT NULL AND s.geom && cut AND ST_Intersects(s.geom, cut) AS touched) t
  LEFT JOIN LATERAL (SELECT d.geom AS g FROM ST_Dump(ST_CollectionExtract(ST_Difference(s.geom, cut), 3)) d
                     WHERE t.touched AND ST_Area(d.geom::geography) >= acre) p ON true
  WHERE NOT EXISTS (SELECT 1 FROM app.settlement_edits a
                    WHERE a.action = 'add' AND a.geom && s.geom AND ST_Intersects(a.geom, s.geom))
    AND (NOT t.touched OR p.g IS NOT NULL);

  -- Replaced outlines, exactly as drawn.
  INSERT INTO se_out (g, source, edit_id, name, settlement_class)
  SELECT geom, 'edited', id, name, settlement_class FROM app.settlement_edits WHERE action = 'replace';

  -- Added settlements: the outline and the computed shapes it overlaps, less anything cut away.
  INSERT INTO se_out (g, source, edit_id, name, settlement_class)
  SELECT CASE WHEN cut IS NULL THEN u.g ELSE ST_Difference(u.g, cut) END, 'edited', a.id, a.name, a.settlement_class
  FROM app.settlement_edits a
  CROSS JOIN LATERAL (SELECT ST_Union(a.geom, coalesce(
           (SELECT ST_Union(s.geom) FROM src_units.settlements s WHERE s.geom && a.geom AND ST_Intersects(s.geom, a.geom)),
           a.geom)) AS g) u
  WHERE a.action = 'add';

  -- Recount what changed: buildings touching the outline, their footprint, and the town holding most of it.
  UPDATE se_out o SET (buildings, footprint_acres) = (
    SELECT count(*)::int, coalesce(sum(ST_Area(b.geom::geography)), 0) / acre
    FROM src_overture.buildings b WHERE b.geom && o.g AND ST_Intersects(b.geom, o.g))
  WHERE o.buildings IS NULL;
  UPDATE se_out o SET town_geoid = c.geoid
  FROM src_census.cousub c
  WHERE o.town_geoid IS NULL AND ST_Intersects(c.geom, ST_PointOnSurface(o.g));

  TRUNCATE src_units.settlements_final;
  INSERT INTO src_units.settlements_final
    (id, town_geoid, buildings, footprint_acres, settlement_class, core_share, source, edit_id, name, geom)
  SELECT row_number() OVER (ORDER BY buildings DESC NULLS LAST)::int, town_geoid, buildings, footprint_acres,
         coalesce(settlement_class, src_units.settlement_class_for(buildings)), core_share,
         source, edit_id, name, ST_Multi(ST_CollectionExtract(g, 3))
  FROM se_out WHERE g IS NOT NULL AND NOT ST_IsEmpty(g);
  ANALYZE src_units.settlements_final;

  SELECT json_build_object(
           'settlements', (SELECT count(*) FROM src_units.settlements_final),
           'edited_settlements', (SELECT count(*) FROM src_units.settlements_final WHERE source = 'edited'),
           'computed', (SELECT count(*) FROM src_units.settlements),
           'edits', (SELECT coalesce(json_object_agg(action, n), '{}'::json)
                     FROM (SELECT action, count(*) AS n FROM app.settlement_edits GROUP BY action) x))
    INTO result;
  RETURN result;
END
$$;
REVOKE ALL ON FUNCTION src_units.apply_settlement_edits() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION src_units.apply_settlement_edits() TO app_rw;
-- core-api reports the counts in the editor (read only).
GRANT USAGE ON SCHEMA src_units TO app_rw;
GRANT SELECT ON src_units.settlements, src_units.settlements_final TO app_rw;
SELECT src_units.apply_settlement_edits();

CREATE VIEW pub.maine_places__settlements AS
SELECT s.id,
       coalesce(s.name, t.name, 'Unnamed') AS town,
       k.name AS county,
       s.settlement_class,
       s.buildings,
       (ST_Area(s.geom::geography) / 4046.8564224)::float8 AS acres,
       s.footprint_acres,
       round((100 * s.core_share)::numeric, 1)::float8 AS dense_core_pct,
       s.source,
       s.geom
FROM src_units.settlements_final s
LEFT JOIN src_census.cousub t ON t.geoid = s.town_geoid
LEFT JOIN src_census.county k ON k.geoid = left(s.town_geoid, 5);

COMMENT ON VIEW pub.maine_places__settlements IS 'maine-places: settlements classified by the Degree of Urbanisation, adapted to Overture building footprints (method v4)';

DROP VIEW IF EXISTS pub.maine_places__density_grid;
CREATE VIEW pub.maine_places__density_grid AS
SELECT id, cell_class, buildings,
       round(density::numeric, 2)::float8 AS buildings_per_ha,
       round((100 * cover)::numeric, 1)::float8 AS cover_pct,
       geom
FROM src_units.settlement_cells;

COMMENT ON VIEW pub.maine_places__density_grid IS 'maine-places: 100 m cells classed by building density over 300 m (Degree of Urbanisation, adapted)';
