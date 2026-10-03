-- Maine Transportation: bridges (MaineDOT); condition is the lowest of the deck, superstructure, substructure and culvert ratings (FHWA good/fair/poor).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_transportation__bridges;
CREATE OR REPLACE VIEW pub.maine_transportation__bridges AS
SELECT id, brdgno AS bridge_no, initcap(brdg_name) AS name, facility, featint AS crosses, yearbuilt AS year_built,
       adttotal AS daily_traffic, suff_rate::float8 AS sufficiency, owner_desc AS owner,
       CASE WHEN least(nullif(left(dkrating_desc, 1), 'N'), nullif(left(suprating_desc, 1), 'N'), nullif(left(subrating_desc, 1), 'N'),
                       nullif(left(culvrating_desc, 1), 'N')) ~ '^[0-4]$' THEN 'poor'
            WHEN least(nullif(left(dkrating_desc, 1), 'N'), nullif(left(suprating_desc, 1), 'N'), nullif(left(subrating_desc, 1), 'N'),
                       nullif(left(culvrating_desc, 1), 'N')) ~ '^[56]$' THEN 'fair'
            WHEN least(nullif(left(dkrating_desc, 1), 'N'), nullif(left(suprating_desc, 1), 'N'), nullif(left(subrating_desc, 1), 'N'),
                       nullif(left(culvrating_desc, 1), 'N')) ~ '^[7-9]$' THEN 'good' ELSE 'not rated' END AS condition,
       geom::geometry(Point, 4326) AS geom
FROM src_mdot.bridges WHERE archived_reason IS NULL;

COMMENT ON VIEW pub.maine_transportation__bridges IS 'maine-transportation: bridges with condition (MaineDOT; lowest NBI component rating)';
