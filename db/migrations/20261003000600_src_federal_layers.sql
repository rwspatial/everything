-- migrate:up
-- Federal layers for Maine: USGS National Transportation Dataset, the HIFLD archive (critical facilities), FEMA NFHL.
-- EIA Energy Atlas layers go to src_energy (exists).
CALL app.ensure_src_schema('src_ntd');
CALL app.ensure_src_schema('src_hifld');
CALL app.ensure_src_schema('src_fema');

-- migrate:down
DROP SCHEMA IF EXISTS src_fema CASCADE;
DROP SCHEMA IF EXISTS src_hifld CASCADE;
DROP SCHEMA IF EXISTS src_ntd CASCADE;
