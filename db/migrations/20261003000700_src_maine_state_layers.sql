-- migrate:up
-- Maine state layers: MEGIS GeoLibrary (boundaries, conserved lands, parcels), MDIFW / Beginning with Habitat,
-- MaineDOT open data, and broadband availability (FCC Broadband Data Collection).
CALL app.ensure_src_schema('src_megis');
CALL app.ensure_src_schema('src_habitat');
CALL app.ensure_src_schema('src_mdot');
CALL app.ensure_src_schema('src_broadband');

-- migrate:down
DROP SCHEMA IF EXISTS src_broadband CASCADE;
DROP SCHEMA IF EXISTS src_mdot CASCADE;
DROP SCHEMA IF EXISTS src_habitat CASCADE;
DROP SCHEMA IF EXISTS src_megis CASCADE;
