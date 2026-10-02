-- migrate:up
-- Census Bureau sources: TIGER/Line geometry and ACS tables from the Census Data API (Maine plan, Phase A).
CALL app.ensure_src_schema('src_census');

-- migrate:down
DROP SCHEMA IF EXISTS src_census CASCADE;
