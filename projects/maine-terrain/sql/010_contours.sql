-- Maine Terrain: 100-ft contour lines -> pub.maine_terrain__contours
-- Applied by `./mapgen apply maine-terrain` (and by `make seed`). Contours come from gdal_contour on the 30 m DEM in
-- metres at 30.48 m steps, so feet are whole hundreds; every fifth line (500 ft) is an index contour.
CREATE OR REPLACE VIEW pub.maine_terrain__contours AS
SELECT id,
       round(elev_m * 3.28084)::integer                AS elev_ft,
       (round(elev_m * 3.28084)::integer % 500 = 0)    AS index_line,
       geom
FROM src_terrain.contours_100ft;

COMMENT ON VIEW pub.maine_terrain__contours IS 'maine-terrain: 100-ft contour lines from the 30 m 3DEP DEM';
