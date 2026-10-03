-- Maine Places: settlement outlines (built-up areas) -> pub.maine_places__settlements, for zooms where 925k building
-- footprints are too dense to draw (z7-12; footprints take over from z13).
-- Method: building points (a point on each footprint, EPSG:26919) clustered statewide with DBSCAN (neighbours within
-- 58 m, at least 4 buildings; 58 m = 25 % lower density than 50 m), then each cluster closed into one shape (buffer 60 m, then -35 m), touching shapes dissolved into one
-- settlement, simplified to 5 m; settlements under 10 buildings are dropped. Scattered rural houses are not a settlement by design.
-- Built into src_units.settlements, and rebuilt only when the building count changes (about two minutes), so
-- `make seed` and `./mapgen apply maine-places` stay quick. To force a rebuild: TRUNCATE src_units.settlements_meta.
CREATE TABLE IF NOT EXISTS src_units.settlements (
  id integer PRIMARY KEY, town_geoid text, buildings integer, footprint_acres float8,
  geom geometry(MultiPolygon, 4326));
CREATE INDEX IF NOT EXISTS settlements_geom_idx ON src_units.settlements USING gist (geom);
CREATE TABLE IF NOT EXISTS src_units.settlements_meta (source_rows bigint, built_at timestamptz);
GRANT SELECT ON src_units.settlements, src_units.settlements_meta TO src_reader;

DO $$
DECLARE src_rows bigint := (SELECT count(*) FROM src_overture.buildings);
BEGIN
  IF src_rows = coalesce((SELECT source_rows FROM src_units.settlements_meta), -1) THEN
    RETURN;
  END IF;
  RAISE NOTICE 'settlements: clustering % buildings', src_rows;
  CREATE TEMP TABLE pts ON COMMIT DROP AS
    SELECT ST_Transform(ST_PointOnSurface(geom), 26919) AS pt, ST_Area(geom::geography) AS m2
    FROM src_overture.buildings;
  CREATE TEMP TABLE cl ON COMMIT DROP AS
    SELECT pt, m2, ST_ClusterDBSCAN(pt, 58, 4) OVER () AS cid FROM pts;
  -- One closed shape per cluster; then shapes that touch or overlap (a city split by parking lots and highways
  -- wider than 50 m) are dissolved into one settlement.
  CREATE TEMP TABLE shapes ON COMMIT DROP AS
    SELECT count(*) AS n, sum(m2) AS m2, ST_Buffer(ST_Buffer(ST_Collect(pt), 60, 4), -35, 4) AS g
    FROM cl WHERE cid IS NOT NULL GROUP BY cid;
  CREATE INDEX ON shapes USING gist (g);
  TRUNCATE src_units.settlements;
  INSERT INTO src_units.settlements (id, town_geoid, buildings, footprint_acres, geom)
  SELECT row_number() OVER (ORDER BY sum(n) DESC)::int, NULL, sum(n)::int, sum(m2) / 4046.8564224,
         ST_Multi(ST_Transform(ST_SimplifyPreserveTopology(ST_Union(g), 5), 4326))
  FROM (SELECT n, m2, g, ST_ClusterDBSCAN(g, 0, 1) OVER () AS sid FROM shapes) m
  GROUP BY sid HAVING sum(n) >= 10;
  -- Name each settlement after the town holding most of it (a point on its surface).
  UPDATE src_units.settlements s SET town_geoid = c.geoid
  FROM src_census.cousub c WHERE ST_Intersects(c.geom, ST_PointOnSurface(s.geom));
  DELETE FROM src_units.settlements_meta;
  INSERT INTO src_units.settlements_meta VALUES (src_rows, now());
END
$$;
ANALYZE src_units.settlements;

DROP VIEW IF EXISTS pub.maine_places__settlements;
CREATE VIEW pub.maine_places__settlements AS
SELECT s.id,
       coalesce(t.name, 'Unnamed') AS town,
       k.name AS county,
       s.buildings,
       (ST_Area(s.geom::geography) / 4046.8564224)::float8 AS acres,
       s.footprint_acres,
       CASE WHEN s.buildings >= 1000 THEN 'City or large town'
            WHEN s.buildings >= 250 THEN 'Town centre'
            WHEN s.buildings >= 50 THEN 'Village'
            ELSE 'Hamlet' END AS size_class,
       s.geom
FROM src_units.settlements s
LEFT JOIN src_census.cousub t ON t.geoid = s.town_geoid
LEFT JOIN src_census.county k ON k.geoid = left(s.town_geoid, 5);

COMMENT ON VIEW pub.maine_places__settlements IS 'maine-places: settlement outlines (built-up areas clustered from Overture building footprints)';
