-- Maine Places: settlement outlines (built-up areas) -> pub.maine_places__settlements, for zooms where 925k building
-- footprints are too dense to draw (z7-12; footprints take over from z13).
-- Method (docs/methods/settlements.json): building footprints (EPSG:26919) clustered statewide with DBSCAN, distance
-- measured edge to edge (neighbours within 45 m, at least 4 buildings), so a school or mill counts by its walls, not
-- its centre. Each cluster's footprints are closed into one shape (buffer 45 m, then -35 m), touching shapes
-- dissolved into one settlement. Large buildings (2000 m2+) left outside but within 100 m of a settlement are attached
-- to the nearest one. Interior holes under max(10 acres, 3 % of the settlement) are filled (no "swiss cheese"; large
-- parks and ponds stay). Simplified to 5 m; settlements under 10 buildings are dropped. Scattered rural houses are not a
-- settlement by design.
-- Built into src_units.settlements, and rebuilt only when the building count or the method version changes (about
-- five minutes), so `make seed` and `./mapgen apply maine-places` stay quick. To force a rebuild:
-- TRUNCATE src_units.settlements_meta.
CREATE TABLE IF NOT EXISTS src_units.settlements (
  id integer PRIMARY KEY, town_geoid text, buildings integer, footprint_acres float8,
  geom geometry(MultiPolygon, 4326));
CREATE INDEX IF NOT EXISTS settlements_geom_idx ON src_units.settlements USING gist (geom);
CREATE TABLE IF NOT EXISTS src_units.settlements_meta (source_rows bigint, built_at timestamptz);
ALTER TABLE src_units.settlements_meta ADD COLUMN IF NOT EXISTS method integer;
GRANT SELECT ON src_units.settlements, src_units.settlements_meta TO src_reader;

-- Fills the interior rings (holes) of a polygon smaller than min_m2 (same units as the geometry, here m2 in
-- EPSG:26919); larger holes are kept.
CREATE OR REPLACE FUNCTION src_units.fill_small_holes(g geometry, min_m2 float8) RETURNS geometry
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT ST_Collect(ST_MakePolygon(ST_ExteriorRing(p.geom),
           ARRAY(SELECT ST_ExteriorRing(h.geom) FROM ST_DumpRings(p.geom) h
                 WHERE h.path[1] > 0 AND ST_Area(h.geom) >= min_m2)))
  FROM ST_Dump(g) p
$$;

DO $$
DECLARE
  src_rows bigint := (SELECT count(*) FROM src_overture.buildings);
  method_version CONSTANT integer := 3;  -- bump when the method below changes, to rebuild on the next apply
BEGIN
  IF EXISTS (SELECT 1 FROM src_units.settlements_meta WHERE source_rows = src_rows AND method = method_version) THEN
    RETURN;
  END IF;
  RAISE NOTICE 'settlements: clustering % buildings (method %)', src_rows, method_version;
  CREATE TEMP TABLE fp ON COMMIT DROP AS
    SELECT ST_Transform(geom, 26919) AS g, ST_Area(geom::geography) AS m2 FROM src_overture.buildings;
  CREATE INDEX ON fp USING gist (g);
  CREATE TEMP TABLE cl ON COMMIT DROP AS
    SELECT g, m2, ST_ClusterDBSCAN(g, 45, 4) OVER () AS cid FROM fp;
  -- One closed shape per cluster; then shapes that touch or overlap (a city split by parking lots and highways
  -- wider than the cluster distance) are dissolved into one settlement.
  CREATE TEMP TABLE shapes ON COMMIT DROP AS
    SELECT count(*) AS n, sum(m2) AS m2, ST_Buffer(ST_Buffer(ST_Collect(g), 45, 4), -35, 4) AS g
    FROM cl WHERE cid IS NOT NULL GROUP BY cid;
  CREATE INDEX ON shapes USING gist (g);
  CREATE TEMP TABLE st ON COMMIT DROP AS
    SELECT sum(n)::int AS n, sum(m2) AS m2, ST_Union(g) AS g
    FROM (SELECT n, m2, g, ST_ClusterDBSCAN(g, 0, 1) OVER () AS sid FROM shapes) m
    GROUP BY sid HAVING sum(n) >= 10;
  ALTER TABLE st ADD COLUMN sid serial;
  CREATE INDEX ON st USING gist (g);
  -- Attach large buildings (a mill or plant at the edge of town, a school on its own lot) left outside but within
  -- 100 m: each joins its nearest settlement through a local closing (60 m) plus a 30 m-wide bridge, so the
  -- settlement stays one piece. "Inside" allows 1 m2 of rounding error.
  CREATE TEMP TABLE att ON COMMIT DROP AS
    SELECT DISTINCT ON (f.g) n.sid, f.g, f.m2, ST_Intersects(f.g, n.g) AS straddles
    FROM fp f CROSS JOIN LATERAL (SELECT sid, g FROM st WHERE ST_DWithin(st.g, f.g, 100) ORDER BY st.g <-> f.g LIMIT 1) n
    WHERE f.m2 >= 2000
      AND NOT EXISTS (SELECT 1 FROM st WHERE ST_Intersects(st.g, f.g) AND ST_Area(ST_Difference(f.g, st.g)) < 1);
  UPDATE st SET g = ST_Union(ARRAY[st.g, x.patch, x.bridge]), n = st.n + x.k, m2 = st.m2 + x.m2
  FROM (SELECT a.sid, count(*) FILTER (WHERE NOT a.straddles)::int AS k,
               coalesce(sum(a.m2) FILTER (WHERE NOT a.straddles), 0) AS m2,
               ST_Union(ST_Collect(a.g), ST_Buffer(ST_Buffer(
                 ST_Union(ST_Collect(a.g), ST_Intersection(s.g, ST_Buffer(ST_Collect(a.g), 150))), 60, 8), -60, 8)) AS patch,
               ST_Buffer(ST_Collect(ST_ShortestLine(a.g, s.g)), 15, 4) AS bridge
        FROM att a JOIN st s USING (sid) GROUP BY a.sid, s.g) x
  WHERE st.sid = x.sid;
  TRUNCATE src_units.settlements;
  INSERT INTO src_units.settlements (id, town_geoid, buildings, footprint_acres, geom)
  -- Holes smaller than max(10 acres, 3 % of the settlement's area) are filled: gaps between building clusters
  -- (parking lots, school fields) made larger settlements look like swiss cheese.
  SELECT row_number() OVER (ORDER BY n DESC)::int, NULL, n, m2 / 4046.8564224,
         ST_Multi(ST_Transform(ST_SimplifyPreserveTopology(
           src_units.fill_small_holes(g, greatest(10 * 4046.8564224, 0.03 * ST_Area(g))), 5), 4326))
  FROM st;
  -- Name each settlement after the town holding most of it (a point on its surface).
  UPDATE src_units.settlements s SET town_geoid = c.geoid
  FROM src_census.cousub c WHERE ST_Intersects(c.geom, ST_PointOnSurface(s.geom));
  DELETE FROM src_units.settlements_meta;
  INSERT INTO src_units.settlements_meta (source_rows, built_at, method) VALUES (src_rows, now(), method_version);
END
$$;
ANALYZE src_units.settlements;

-- Manual edits (app.settlement_edits, drawn in /admin/methods/settlements/edit) applied on top of the computed
-- settlements into src_units.settlements_final, which the map reads. Applying takes seconds (no re-clustering), so
-- core-api calls it after every edit; it is SECURITY DEFINER because core-api cannot write src_units.
--   remove   computed settlements are cut away inside the polygon
--   replace  cut away likewise, then the drawn outline (exact, as drawn) becomes a settlement
--   add      the drawn outline plus every computed settlement it overlaps, as one settlement
-- What is left of a partly cut settlement stays a settlement when it is at least 1 acre; edited settlements get
-- their building count and footprint recounted, and a name or size class from the edit when one was given.
CREATE TABLE IF NOT EXISTS src_units.settlements_final (
  id integer PRIMARY KEY, town_geoid text, buildings integer, footprint_acres float8,
  source text NOT NULL, edit_id bigint, name text, size_class text, geom geometry(MultiPolygon, 4326));
CREATE INDEX IF NOT EXISTS settlements_final_geom_idx ON src_units.settlements_final USING gist (geom);
GRANT SELECT ON src_units.settlements_final TO src_reader;

CREATE OR REPLACE FUNCTION src_units.apply_settlement_edits() RETURNS json
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  acre CONSTANT float8 := 4046.8564224;
  cut geometry;
  result json;
BEGIN
  CREATE TEMP TABLE IF NOT EXISTS se_out (g geometry, buildings integer, footprint_acres float8, town_geoid text,
                                          source text, edit_id bigint, name text, size_class text);
  TRUNCATE se_out;
  SELECT ST_Union(geom) INTO cut FROM app.settlement_edits WHERE action IN ('replace', 'remove');

  -- Computed settlements: untouched ones as they are; partly cut ones keep their parts of 1 acre or more
  -- (recounted below); those an "add" absorbs are left to that add.
  INSERT INTO se_out (g, buildings, footprint_acres, town_geoid, source)
  SELECT CASE WHEN touched THEN p.g ELSE s.geom END,
         CASE WHEN touched THEN NULL ELSE s.buildings END,
         CASE WHEN touched THEN NULL ELSE s.footprint_acres END,
         CASE WHEN touched THEN NULL ELSE s.town_geoid END,
         CASE WHEN touched THEN 'edited' ELSE 'computed' END
  FROM src_units.settlements s
  CROSS JOIN LATERAL (SELECT cut IS NOT NULL AND s.geom && cut AND ST_Intersects(s.geom, cut) AS touched) t
  LEFT JOIN LATERAL (SELECT d.geom AS g FROM ST_Dump(ST_CollectionExtract(ST_Difference(s.geom, cut), 3)) d
                     WHERE t.touched AND ST_Area(d.geom::geography) >= acre) p ON true
  WHERE NOT EXISTS (SELECT 1 FROM app.settlement_edits a
                    WHERE a.action = 'add' AND a.geom && s.geom AND ST_Intersects(a.geom, s.geom))
    AND (NOT t.touched OR p.g IS NOT NULL);

  -- Replaced outlines, exactly as drawn.
  INSERT INTO se_out (g, source, edit_id, name, size_class)
  SELECT geom, 'edited', id, name, size_class FROM app.settlement_edits WHERE action = 'replace';

  -- Added settlements: the outline and the computed shapes it overlaps, less anything cut away.
  INSERT INTO se_out (g, source, edit_id, name, size_class)
  SELECT CASE WHEN cut IS NULL THEN u.g ELSE ST_Difference(u.g, cut) END, 'edited', a.id, a.name, a.size_class
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
  INSERT INTO src_units.settlements_final (id, town_geoid, buildings, footprint_acres, source, edit_id, name, size_class, geom)
  SELECT row_number() OVER (ORDER BY buildings DESC NULLS LAST)::int, town_geoid, buildings, footprint_acres,
         source, edit_id, name, size_class, ST_Multi(ST_CollectionExtract(g, 3))
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

DROP VIEW IF EXISTS pub.maine_places__settlements;
CREATE VIEW pub.maine_places__settlements AS
SELECT s.id,
       coalesce(s.name, t.name, 'Unnamed') AS town,
       k.name AS county,
       s.buildings,
       (ST_Area(s.geom::geography) / 4046.8564224)::float8 AS acres,
       s.footprint_acres,
       coalesce(s.size_class,
         CASE WHEN s.buildings >= 1000 THEN 'City or large town'
              WHEN s.buildings >= 250 THEN 'Town centre'
              WHEN s.buildings >= 50 THEN 'Village'
              ELSE 'Hamlet' END) AS size_class,
       s.source,
       s.geom
FROM src_units.settlements_final s
LEFT JOIN src_census.cousub t ON t.geoid = s.town_geoid
LEFT JOIN src_census.county k ON k.geoid = left(s.town_geoid, 5);

COMMENT ON VIEW pub.maine_places__settlements IS 'maine-places: settlement outlines (built-up areas clustered from Overture building footprints)';
