-- Maine Water: dams from the USACE National Inventory of Dams (HIFLD archive).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_water__dams;
CREATE OR REPLACE VIEW pub.maine_water__dams AS
SELECT id, initcap(name) AS name, river_or_stream AS river, hazard_potential AS hazard, primary_purpose AS purpose,
       primary_owner_type AS owner_type, nid_height::integer AS height_ft, nid_storage::float8 AS storage_acre_ft,
       year_completed, condition_assessment AS condition, nidid, geom AS geom
FROM src_hifld.dams WHERE state = 'Maine';

COMMENT ON VIEW pub.maine_water__dams IS 'maine-water: dams (National Inventory of Dams, via HIFLD)';
