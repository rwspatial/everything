-- Maine Energy: pipelines (EIA Energy Atlas).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_energy__pipelines;
CREATE OR REPLACE VIEW pub.maine_energy__pipelines AS
SELECT 'ng-' || id AS id, 'natural gas' AS product, operator, typepipe AS kind, ST_Force2D(geom)::geometry(MultiLineString, 4326) AS geom
FROM src_energy.natural_gas_pipelines
UNION ALL
SELECT 'pp-' || id, 'petroleum products', opername, pipename, ST_Force2D(geom)::geometry(MultiLineString, 4326)
FROM src_energy.petroleum_pipelines;

COMMENT ON VIEW pub.maine_energy__pipelines IS 'maine-energy: natural gas and petroleum product pipelines';
