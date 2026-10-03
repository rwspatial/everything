-- Maine Habitat: concentrations of at-risk species and habitats (BwH).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_habitat__at_risk_concentrations;
CREATE OR REPLACE VIEW pub.maine_habitat__at_risk_concentrations AS
SELECT id, sum_score::float8 AS score, etsc, viable_rare_plant_spp AS rare_plants, rare_nc AS rare_communities, multiple_sig_habs, geom AS geom FROM src_habitat.at_risk_concentrations;

COMMENT ON VIEW pub.maine_habitat__at_risk_concentrations IS 'maine-habitat: concentrations of at-risk species and habitats (BwH hex grid)';
