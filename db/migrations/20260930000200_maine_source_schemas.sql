-- migrate:up
-- Source schemas for the Maine ETL catalog (.claude/plans/maine-etl-catalog.plan.md, phases E1-E2).
CALL app.ensure_src_schema('src_e911');     -- E911 road centerlines and address points (Maine GeoLibrary)
CALL app.ensure_src_schema('src_dmr');      -- Dept. of Marine Resources: shellfish growing areas, aquaculture
CALL app.ensure_src_schema('src_bpl');      -- Bureau of Parks and Lands: public lands, boat launches, trails
CALL app.ensure_src_schema('src_nwi');      -- National Wetlands Inventory (USFWS)
CALL app.ensure_src_schema('src_attains');  -- EPA ATTAINS assessment units (Maine DEP integrated report)
CALL app.ensure_src_schema('src_energy');   -- US Wind Turbine Database (USGS)
CALL app.ensure_src_schema('src_climate');  -- USDA plant hardiness zones (PRISM/OSU)

-- migrate:down
DROP SCHEMA IF EXISTS src_climate CASCADE;
DROP SCHEMA IF EXISTS src_energy CASCADE;
DROP SCHEMA IF EXISTS src_attains CASCADE;
DROP SCHEMA IF EXISTS src_nwi CASCADE;
DROP SCHEMA IF EXISTS src_bpl CASCADE;
DROP SCHEMA IF EXISTS src_dmr CASCADE;
DROP SCHEMA IF EXISTS src_e911 CASCADE;
