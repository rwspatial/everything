-- Route badges for every map (drawn by the viewer as a global overlay, not a project layer): MaineDOT public road
-- segments merged per numbered route, as kind (interstate | us | state) + ref ("95", "2", "26").
-- A materialized view: merging lines per route statewide is far too slow to do per tile. `./mapgen apply
-- maine-transportation` rebuilds it (re-run after re-importing MaineDOT roads).
DROP MATERIALIZED VIEW IF EXISTS pub.maine_transportation__route_shields;
CREATE MATERIALIZED VIEW pub.maine_transportation__route_shields AS
WITH routes AS (
  -- From the source table, not pub.maine_transportation__public_roads: a materialized view on that view would stop
  -- 005_public_roads.sql from dropping and recreating it (make seed).
  SELECT CASE WHEN prirtename ~ '^INT ' THEN 'interstate' WHEN prirtename ~ '^US ' THEN 'us' ELSE 'state' END AS kind,
         substring(prirtename FROM '^(?:INT|US|ST RTE) (\d+[A-Z]?)') AS ref,
         geom
  FROM src_mdot.public_roads
  WHERE prirtename ~ '^(INT|US|ST RTE) \d'
), merged AS (
  -- Merge each route into continuous lines, then cut long ones so tiles clip small pieces.
  SELECT kind, ref, (ST_Dump(ST_LineMerge(ST_Union(geom)))).geom AS geom
  FROM routes GROUP BY kind, ref
), pieces AS (
  SELECT kind, ref, ST_Subdivide(geom, 512) AS geom
  FROM merged
  WHERE ST_Length(geom::geography) > 300   -- skip stubs: too short to carry a label
)
SELECT row_number() OVER (ORDER BY kind, ref)::int AS id, kind, ref,
       CASE kind WHEN 'interstate' THEN 1 WHEN 'us' THEN 2 ELSE 3 END AS rank,
       geom::geometry(LineString, 4326) AS geom
FROM pieces;

CREATE UNIQUE INDEX ON pub.maine_transportation__route_shields (id);
CREATE INDEX ON pub.maine_transportation__route_shields USING gist (geom);
COMMENT ON MATERIALIZED VIEW pub.maine_transportation__route_shields IS 'maine-transportation: numbered routes (interstate, US, state) for the viewer''s route badges (MaineDOT)';
