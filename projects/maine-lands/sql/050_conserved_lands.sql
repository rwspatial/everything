-- Maine Lands: all conserved lands, Maine GeoLibrary (state, federal, municipal, land trust).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_lands__conserved_lands;
CREATE OR REPLACE VIEW pub.maine_lands__conserved_lands AS
SELECT id, coalesce(nullif(trim(parcel_name), ''), nullif(trim(project), ''), 'Conserved land') AS name,
       designation, coalesce(nullif(trim(hold1_type), ''), 'Other') AS holder_type, hold1_name AS holder,
       CASE WHEN cons1_type ILIKE '%easement%' THEN 'easement' ELSE 'fee' END AS interest,
       CASE WHEN pub_access ILIKE 'allow%' OR pub_access ILIKE 'water access%' OR pub_access ILIKE 'guaranteed%' THEN 'allowed'
            WHEN pub_access ILIKE 'no %' OR pub_access ILIKE 'not allowed%' THEN 'none'
            WHEN pub_access ILIKE 'restrict%' OR pub_access ILIKE 'contact%' OR pub_access ILIKE 'private%' THEN 'ask the owner'
            ELSE 'unknown' END AS public_access,
       pub_access AS access_notes, round(calc_ac::numeric)::float8 AS acres, acq_year, gap_status,
       ST_Force2D(geom)::geometry(MultiPolygon, 4326) AS geom
FROM src_megis.conserved_lands;

COMMENT ON VIEW pub.maine_lands__conserved_lands IS 'maine-lands: conserved lands (MEGIS)';
