-- Maine Water: watersheds from the USGS Watershed Boundary Dataset (WBD) -> pub.maine_water__watersheds (HUC-8
-- subbasins) and pub.maine_water__subwatersheds (HUC-12), every unit touching Maine.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_water__watersheds;
CREATE VIEW pub.maine_water__watersheds AS
SELECT id, huc8, name, round((areasqkm * 0.386102)::numeric)::float8 AS area_sqmi, states, geom
FROM src_hydro.wbd_huc8;

DROP VIEW IF EXISTS pub.maine_water__subwatersheds;
CREATE VIEW pub.maine_water__subwatersheds AS
SELECT id, huc12, name, left(huc12, 8) AS huc8, round((areasqkm * 0.386102)::numeric)::float8 AS area_sqmi, geom
FROM src_hydro.wbd_huc12;

COMMENT ON VIEW pub.maine_water__watersheds IS 'maine-water: HUC-8 watersheds touching Maine (USGS WBD)';
COMMENT ON VIEW pub.maine_water__subwatersheds IS 'maine-water: HUC-12 sub-watersheds touching Maine (USGS WBD)';
