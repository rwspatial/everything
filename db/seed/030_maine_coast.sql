-- Maine Coast example project (draft): DMR shellfish + aquaculture, boat launches.
-- Personal names in the DMR sources (LPA license holders, lease holders) are deliberately NOT published.

CREATE OR REPLACE VIEW pub.maine_coast__growing_areas AS
SELECT id, label, sma, acres, geom FROM src_dmr.growing_areas;

CREATE OR REPLACE VIEW pub.maine_coast__shellfish_classes AS
SELECT id, ga AS growing_area, ga_section AS section, nssp,
       CASE nssp WHEN 'A' THEN 'Approved' WHEN 'CA' THEN 'Conditionally approved'
                 WHEN 'CR' THEN 'Conditionally restricted' WHEN 'R' THEN 'Restricted'
                 WHEN 'P' THEN 'Prohibited' ELSE nssp END AS classification,
       status, d_effective AS effective, acres, geom
FROM src_dmr.nssp_classifications_2022;
COMMENT ON VIEW pub.maine_coast__shellfish_classes IS
  'NSSP classifications 2022 (Maine DMR). NOT real-time open/closed status; DMR issues closures daily.';

CREATE OR REPLACE VIEW pub.maine_coast__aquaculture_leases AS
SELECT id, site_id, primarysp AS species,
       CASE status WHEN 'A' THEN 'Active' WHEN 'P' THEN 'Pending' ELSE status END AS status,
       lease_type, waterbody, city AS town, acres, expiration, geom
FROM src_dmr.aquaculture_leases;

CREATE OR REPLACE VIEW pub.maine_coast__lpa_sites AS
SELECT id, site_id, species, lease_type, status, waterbody, site_town AS town, gear, geom
FROM src_dmr.lpa_sites;

CREATE OR REPLACE VIEW pub.maine_coast__boat_launches AS
SELECT id, water_body, mcd AS town, county, type, typeramp AS ramp, tide_combo AS tide, vehpark AS parking, geom
FROM src_bpl.boat_launches;
