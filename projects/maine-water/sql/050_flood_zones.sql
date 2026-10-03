-- Maine Water: FEMA National Flood Hazard Layer flood zones (special flood hazard areas and the 0.2% chance floodplain).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_water__flood_zones;
CREATE OR REPLACE VIEW pub.maine_water__flood_zones AS
SELECT id, fld_zone AS zone, zone_subty AS subtype,
       CASE WHEN fld_zone LIKE 'V%' THEN 'coastal high hazard'
            WHEN zone_subty ILIKE '%floodway%' THEN 'floodway'
            WHEN fld_zone LIKE 'A%' THEN '1% annual chance'
            WHEN zone_subty ILIKE '0.2 PCT%' THEN '0.2% annual chance'
            WHEN fld_zone = 'D' THEN 'undetermined' END AS hazard,
       nullif(static_bfe, -9999)::float8 AS base_flood_elev_ft, v_datum, dfirm_id,
       ST_Force2D(geom)::geometry(MultiPolygon, 4326) AS geom
FROM src_fema.flood_zones
WHERE fld_zone LIKE 'V%' OR fld_zone LIKE 'A%' OR fld_zone = 'D' OR zone_subty ILIKE '0.2 PCT%';

COMMENT ON VIEW pub.maine_water__flood_zones IS 'maine-water: FEMA flood hazard zones (NFHL), minimal-hazard zone X omitted';
