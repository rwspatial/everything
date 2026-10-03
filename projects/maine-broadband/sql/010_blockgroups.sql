-- Maine Broadband: FCC BDC availability by block group.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_broadband__blockgroups;
CREATE OR REPLACE VIEW pub.maine_broadband__blockgroups AS
SELECT id, geoid, countyname AS county, totalbsls AS locations, servedbsls AS served, underservedbsls AS underserved,
       unservedbsls AS unserved,
       round(100.0 * (unservedbsls + underservedbsls) / nullif(totalbsls, 0), 1)::float8 AS pct_not_served,
       round(100.0 * unservedbsls / nullif(totalbsls, 0), 1)::float8 AS pct_unserved,
       round(100.0 * servedbslsfiber / nullif(totalbsls, 0), 1)::float8 AS pct_fiber,
       geom AS geom
FROM src_broadband.fcc_blockgroups WHERE totalbsls > 0;

COMMENT ON VIEW pub.maine_broadband__blockgroups IS 'maine-broadband: broadband availability by block group (FCC BDC)';
