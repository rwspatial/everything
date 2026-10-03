-- Maine Transportation: MaineDOT public roads by functional class.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__public_roads;
CREATE OR REPLACE VIEW pub.maine_transportation__public_roads AS
SELECT id, initcap(strtname) AS name, prirtename AS route,
       CASE fedfunccls WHEN 'Other Freeway or Expressway' THEN 'Other freeway / expressway'
                       WHEN 'Other Principal Arterial' THEN 'Other principal arterial'
                       WHEN 'Minor Arterial' THEN 'Minor arterial' WHEN 'Major Collector' THEN 'Major collector'
                       WHEN 'Minor Collector' THEN 'Minor collector' ELSE fedfunccls END AS functional_class,
       initcap(townname) AS town, jurisdictn AS jurisdiction, faadt AS aadt, num_lanes AS lanes, speed_lim AS speed_limit,
       nhs_status AS nhs, geom AS geom
FROM src_mdot.public_roads;

COMMENT ON VIEW pub.maine_transportation__public_roads IS 'maine-transportation: MaineDOT public roads';
