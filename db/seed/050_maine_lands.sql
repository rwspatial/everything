-- Maine Lands example project (draft): BPL public lands, plant hardiness zones.

CREATE OR REPLACE VIEW pub.maine_lands__public_lands AS
SELECT id, parcel_name, designation, hold1_name AS holder, pub_access AS public_access,
       round(calc_ac::numeric, 1) AS acres, geom
FROM src_bpl.lands;

CREATE OR REPLACE VIEW pub.maine_lands__hardiness_zones AS
SELECT id, zone, zonetitle AS title, trange AS min_temp_range_f, geom FROM src_climate.hardiness_zones_2023;
