-- Maine Water example project (draft): NWI wetlands, EPA ATTAINS assessed waters.

CREATE OR REPLACE VIEW pub.maine_water__wetlands AS
SELECT id, wetland_type, attribute AS nwi_code, acres, geom FROM src_nwi.wetlands;

CREATE OR REPLACE VIEW pub.maine_water__assessed_streams AS
SELECT id, assessmentunitname AS name, assessmentunitidentifier AS unit_id, overallstatus AS status,
       ircategory AS category, on303dlist AS on_303d_list, reportingcycle AS cycle, waterbodyreportlink AS report, geom
FROM src_attains.assessment_lines;

CREATE OR REPLACE VIEW pub.maine_water__assessed_lakes AS
SELECT id, assessmentunitname AS name, assessmentunitidentifier AS unit_id, overallstatus AS status,
       ircategory AS category, on303dlist AS on_303d_list, reportingcycle AS cycle, waterbodyreportlink AS report, geom
FROM src_attains.assessment_areas;
