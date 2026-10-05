-- Maine Coast: sea level rise and storm surge inundation scenarios (Maine Geological Survey, 2018) ->
-- pub.maine_coast__slr_scenarios. Each scenario is the area below the Highest Astronomical Tide (HAT) plus N feet;
-- higher scenarios contain the lower ones. slr_ft is the rise in feet (0 = HAT itself); scenario_rank numbers the scenarios 0-6 (MapLibre styles match on integers). Connectivity notes are normalized
-- (the source mixes case and has a typo): tidally connected areas flood directly; low-lying unconnected areas, back-barrier
-- wetlands and one-way freshwater ponds/wetlands are below the water level but behind a barrier or culvert.
-- planning_target links the scenarios to the Maine Climate Council's sea level rise planning targets (2020):
-- commit to manage 1.5 ft by 2050 and 3.9 ft by 2100; prepare to manage 3.0 ft by 2050 and 8.8 ft by 2100.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_coast__slr_scenarios;
CREATE VIEW pub.maine_coast__slr_scenarios AS
SELECT s.id,
       s.scenario,
       f.slr_ft,
       array_position(ARRAY[0, 1.2, 1.6, 3.9, 6.1, 8.8, 10.9]::float8[], f.slr_ft) - 1 AS scenario_rank,
       CASE f.slr_ft WHEN 0 THEN 'Today''s highest tide'
                     WHEN 1.6 THEN 'About 2050, commit to manage (1.5 ft)'
                     WHEN 3.9 THEN '2100 commit to manage (3.9 ft); beyond 2050 prepare to manage (3 ft)'
                     WHEN 8.8 THEN '2100, prepare to manage (8.8 ft)'
                     ELSE 'Sensitivity scenario' END AS planning_target,
       CASE WHEN s.notes ILIKE 'tidally connected%' OR s.notes IS NULL THEN 'Tidally connected'
            WHEN s.notes ILIKE 'low-lying%' THEN 'Low-lying, not tidally connected'
            WHEN s.notes ILIKE 'back-barrier%' THEN 'Back-barrier wetland'
            WHEN s.notes ILIKE 'freshwater%' THEN 'Freshwater pond or wetland (one-way flow)'
            ELSE s.notes END AS connectivity,
       (ST_Area(s.geom::geography) / 4046.8564224)::float8 AS acres,
       s.geom
FROM src_mgs.slr_scenarios s
CROSS JOIN LATERAL (SELECT CASE WHEN s.scenario = 'HAT' THEN 0::float8
                                ELSE substring(s.scenario FROM 'Plus ([0-9.]+) Feet')::float8 END AS slr_ft) f;

COMMENT ON VIEW pub.maine_coast__slr_scenarios IS 'maine-coast: sea level rise and storm surge scenarios (MGS 2018, HAT + 0 to 10.9 ft)';
