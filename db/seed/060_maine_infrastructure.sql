-- Maine Infrastructure example project (draft): E911 roads by class, address points, wind turbines.
-- Roads are split by class so low zooms only fetch the few thousand major roads.

CREATE OR REPLACE VIEW pub.maine_infrastructure__roads_primary AS
SELECT id, rdname AS name, rdclass AS class, town, speed, geom FROM src_e911.roads WHERE rdclass IN ('Primary', 'Ramp');

CREATE OR REPLACE VIEW pub.maine_infrastructure__roads_secondary AS
SELECT id, rdname AS name, rdclass AS class, town, speed, geom FROM src_e911.roads WHERE rdclass = 'Secondary';

CREATE OR REPLACE VIEW pub.maine_infrastructure__roads_local AS
SELECT id, rdname AS name, rdclass AS class, town, speed, geom FROM src_e911.roads
WHERE rdclass IS DISTINCT FROM 'Primary' AND rdclass IS DISTINCT FROM 'Ramp' AND rdclass IS DISTINCT FROM 'Secondary';

CREATE OR REPLACE VIEW pub.maine_infrastructure__addresses AS
SELECT id, address, town, zipcode, place_type, geom FROM src_e911.addresses;

CREATE OR REPLACE VIEW pub.maine_infrastructure__wind_turbines AS
SELECT id, p_name AS project, p_year AS year, t_manu AS manufacturer, t_model AS model,
       t_cap AS capacity_kw, t_hh AS hub_height_m, t_rd AS rotor_m, geom
FROM src_energy.wind_turbines;
