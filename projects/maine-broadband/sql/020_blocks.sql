-- Maine Broadband: FCC BDC availability by census block.
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_broadband__blocks;
CREATE OR REPLACE VIEW pub.maine_broadband__blocks AS
SELECT id, geoid, countyname AS county, totalbsls AS locations, servedbsls AS served, underservedbsls AS underserved,
       unservedbsls AS unserved,
       round(100.0 * (unservedbsls + underservedbsls) / nullif(totalbsls, 0), 1)::float8 AS pct_not_served,
       round(100.0 * unservedbsls / nullif(totalbsls, 0), 1)::float8 AS pct_unserved,
       round(100.0 * servedbslsfiber / nullif(totalbsls, 0), 1)::float8 AS pct_fiber,
       geom AS geom
FROM src_broadband.fcc_blocks WHERE totalbsls > 0;

COMMENT ON VIEW pub.maine_broadband__blocks IS 'maine-broadband: broadband availability by census block (FCC BDC)';
