-- Maine Critical Facilities: emergency shelters (HIFLD).
-- Numbers styled in the browser must be float8 or integer: tiPG writes numeric columns into tiles as text.
DROP VIEW IF EXISTS pub.maine_facilities__shelters;
CREATE OR REPLACE VIEW pub.maine_facilities__shelters AS
SELECT id, initcap(shelter_name) AS name, initcap(city) AS city, evacuation_capacity, post_impact_capacity,
       ada_compliant, generator_onsite, pet_accommodations_desc AS pets, geom AS geom
FROM src_hifld.shelters;

COMMENT ON VIEW pub.maine_facilities__shelters IS 'maine-facilities: emergency shelters (National Shelter System via HIFLD)';
