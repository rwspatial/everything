-- migrate:up
-- Source schemas for the 2026-10-05 data batch (recipes me_dep_*, me_history_*, me_mgs_*, me_dhhs_*, me_cdc_*,
-- me_doe_*, me_elections_*): DEP contamination, PFAS, dams, lakes and recycling; historic places; Maine Geological
-- Survey geology, aquifers and wells; child care; CDC PLACES health; school units; congressional districts and returns.
CALL app.ensure_src_schema('src_dep');
CALL app.ensure_src_schema('src_history');
CALL app.ensure_src_schema('src_mgs');
CALL app.ensure_src_schema('src_dhhs');
CALL app.ensure_src_schema('src_health');
CALL app.ensure_src_schema('src_education');
CALL app.ensure_src_schema('src_elections');

-- migrate:down
-- Schemas are left in place (they may hold imported tables); drop them by hand if really unused.
SELECT 1;
