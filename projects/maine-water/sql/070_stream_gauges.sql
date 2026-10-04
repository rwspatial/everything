-- Maine Water: active USGS stream gauges -> pub.maine_water__stream_gauges. A gauge is active when it reports
-- streamflow (parameter 00060) currently: the latest-continuous snapshot (me_usgs_latest_flow) joined to the
-- Maine stream monitoring locations (me_usgs_stream_sites) for name and drainage area. Readings are provisional and as
-- of the last import (`make import-recipe r=me_usgs_latest_flow` with --redownload refreshes them).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_water__stream_gauges;
CREATE VIEW pub.maine_water__stream_gauges AS
SELECT s.id,
       s.monitoring_location_number AS site_no,
       s.monitoring_location_name AS name,
       s.county_name AS county,
       s.drainage_area::float8 AS drainage_sqmi,
       CASE WHEN f.value ~ '^-?[0-9]+(\.[0-9]+)?$' THEN f.value::float8 END AS flow_cfs,
       CASE WHEN f.value ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN f.value || ' ft³/s at ' || to_char(f.time AT TIME ZONE 'America/New_York', 'YYYY-MM-DD HH24:MI') || ' ET'
            ELSE 'no current reading' END AS latest,
       'https://waterdata.usgs.gov/monitoring-location/' || s.monitoring_location_number AS link,
       s.geom
FROM src_hydro.usgs_stream_sites s
JOIN src_hydro.usgs_latest_flow f ON f.monitoring_location_id = s.source_id
-- latest-continuous also lists series that stopped long ago (e.g. 1991): active = a reading within 7 days of the
-- snapshot's newest one (relative to the snapshot, so an old snapshot does not empty the layer).
WHERE f.time >= (SELECT max(time) FROM src_hydro.usgs_latest_flow) - interval '7 days';

COMMENT ON VIEW pub.maine_water__stream_gauges IS 'maine-water: active USGS stream gauges with the latest streamflow (provisional)';
