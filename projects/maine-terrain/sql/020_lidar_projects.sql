-- Maine Terrain: USGS 3DEP lidar collections (work-unit footprints) -> pub.maine_terrain__lidar_projects
-- Applied by `./mapgen apply maine-terrain`. Quality level (QL 1 densest .. QL 3) and collection dates per work unit.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_terrain__lidar_projects;
CREATE OR REPLACE VIEW pub.maine_terrain__lidar_projects AS
SELECT id,
       workunit,
       project,
       coalesce(ql, 'Other')                                   AS ql,
       extract(year FROM collect_end)::integer                 AS year,
       dem_gsd_meters::float8                                  AS dem_m,
       concat_ws(', ', to_char(collect_start, 'YYYY-MM-DD') || ' to ' || to_char(collect_end, 'YYYY-MM-DD'),
                 dem_gsd_meters || ' m DEM')                   AS collected,
       metadata_link,
       geom
FROM src_terrain.lidar_projects;

COMMENT ON VIEW pub.maine_terrain__lidar_projects IS 'maine-terrain: USGS 3DEP lidar work units covering Maine';
