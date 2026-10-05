-- Land cover and crops by county, for the Maine Land Cover charts. The layers are rasters (files), so the areas come
-- from src_raster.class_area (scripts/geoimport.py class-stats, run when the NLCD and CDL recipes build their COGs).
-- Labels match the map legend (project.json categories). Each row carries its county outline so the charts' "In view"
-- scope works (a county counts when it touches the map frame).

DROP VIEW IF EXISTS pub.maine_landcover__land_cover;
CREATE VIEW pub.maine_landcover__land_cover AS
WITH labels(value, label, cover_group) AS (VALUES
    (11, 'Open water', 'Water'),
    (12, 'Perennial ice/snow', 'Water'),
    (21, 'Developed, open space', 'Developed'),
    (22, 'Developed, low intensity', 'Developed'),
    (23, 'Developed, medium intensity', 'Developed'),
    (24, 'Developed, high intensity', 'Developed'),
    (31, 'Barren land', 'Barren'),
    (41, 'Deciduous forest', 'Forest'),
    (42, 'Evergreen forest', 'Forest'),
    (43, 'Mixed forest', 'Forest'),
    (52, 'Shrub/scrub', 'Shrub and grassland'),
    (71, 'Grassland/herbaceous', 'Shrub and grassland'),
    (81, 'Pasture/hay', 'Agriculture'),
    (82, 'Cultivated crops', 'Agriculture'),
    (90, 'Woody wetlands', 'Wetland'),
    (95, 'Emergent herbaceous wetlands', 'Wetland'))
SELECT row_number() OVER (ORDER BY a.county_geoid, a.value)::int AS id,
       k.name AS county, coalesce(l.label, 'Class ' || a.value) AS land_cover,
       coalesce(l.cover_group, 'Other') AS cover_group, a.acres, k.geom
FROM src_raster.class_area a
JOIN src_census.county k ON k.geoid = a.county_geoid
LEFT JOIN labels l ON l.value = a.value
WHERE a.cog = 'maine/nlcd_2025_landcover';

DROP VIEW IF EXISTS pub.maine_landcover__crops;
CREATE VIEW pub.maine_landcover__crops AS
WITH labels(value, label) AS (VALUES
    (1, 'Corn'),
    (4, 'Sorghum'),
    (5, 'Soybeans'),
    (6, 'Sunflower'),
    (12, 'Sweet corn'),
    (21, 'Barley'),
    (23, 'Spring wheat'),
    (24, 'Winter wheat'),
    (27, 'Rye'),
    (28, 'Oats'),
    (30, 'Speltz'),
    (35, 'Mustard'),
    (36, 'Alfalfa'),
    (37, 'Other hay / non-alfalfa'),
    (39, 'Buckwheat'),
    (41, 'Sugar beets'),
    (42, 'Dry beans'),
    (43, 'Potatoes'),
    (47, 'Misc. vegetables and fruits'),
    (58, 'Clover / wildflowers'),
    (59, 'Sod / grass seed'),
    (61, 'Fallow / idle cropland'),
    (68, 'Apples'),
    (69, 'Grapes'),
    (70, 'Christmas trees'),
    (71, 'Other tree crops'),
    (77, 'Pears'),
    (92, 'Aquaculture'),
    (111, 'Open water'),
    (121, 'Developed, open space'),
    (122, 'Developed, low intensity'),
    (123, 'Developed, medium intensity'),
    (124, 'Developed, high intensity'),
    (131, 'Barren'),
    (141, 'Deciduous forest'),
    (142, 'Evergreen forest'),
    (143, 'Mixed forest'),
    (152, 'Shrubland'),
    (176, 'Grass / pasture'),
    (190, 'Woody wetlands'),
    (195, 'Herbaceous wetlands'),
    (206, 'Carrots'),
    (208, 'Garlic'),
    (214, 'Broccoli'),
    (220, 'Plums'),
    (221, 'Strawberries'),
    (242, 'Blueberries'),
    (244, 'Cauliflower'),
    (246, 'Radishes'))
SELECT row_number() OVER (ORDER BY a.county_geoid, a.value)::int AS id,
       k.name AS county, coalesce(l.label, 'Class ' || a.value) AS crop, a.acres, k.geom
FROM src_raster.class_area a
JOIN src_census.county k ON k.geoid = a.county_geoid
LEFT JOIN labels l ON l.value = a.value
WHERE a.cog = 'maine/cdl_2025'
  AND a.value NOT IN (61, 63, 64, 65, 81, 82, 83, 87, 88, 92, 111, 112, 121, 122, 123, 124, 131, 141, 142, 143, 152, 176, 190, 195);
