// Site identity: the one place to change names, copy and contact details.
// Empty strings are skipped on the page, so fill in only what you want public.

export const site = {
	/** Your name. When set, the landing page leads with it (for employers) and the studio becomes a subline. */
	person: '',
	/** Role shown next to your name. */
	role: 'Geospatial engineer',
	/** Practice / studio name, used in the header and page titles. */
	studio: 'Downeast Geospatial',
	location: 'Ellsworth, ME',
	/** One line under the name: what the practice and this platform do. */
	headline: 'Geospatial modeling, cartography & reporting',
	tagline:
		'A platform for building geospatial models, maps and reports fast: from raw public data to live analyses, polished cartography and print-ready reports, in R, Python, PostGIS, Svelte, MapLibre and D3.',

	/** Three things the platform does, shown on the landing page. */
	pillars: [
		{
			title: 'Model',
			body: 'Suitability, risk and change models in R and Python, run against PostGIS and cloud rasters: agricultural potential and wildfire fuel hazard for any parcel, town vulnerability assessments, settlement outlines. Every method is documented and every run tracked.'
		},
		{
			title: 'Map',
			body: 'Interactive maps in MapLibre and Svelte, styled to cartographic standards and served live from PostGIS: vector tiles, cloud-optimized rasters, and map designs that turn a town or parcel into a finished map in minutes.'
		},
		{
			title: 'Report',
			body: 'Custom reporting on the same data: D3 charts computed on the fly for any area, analysis reports for a parcel or town, and PDF reports printed straight from the map.'
		}
	],

	/** Draft copy; rewrite in your own voice. */
	about: [
		'This site is a fully independent cloud GIS: its own spatial database, map and tile server, analysis workers and report printer, built entirely from open-source software, with no proprietary GIS platform or licences underneath. It takes public data from dozens of state and federal sources, models it, maps it and reports on it. New analyses, map designs and reports are built on what is already there, so an idea becomes a live map or a parcel report in days, not months.',
		'It is built to stay open and adaptable: R and Python for analysis, PostGIS for data, Svelte, MapLibre and D3 for the web, and cloud storage for rasters. The same pieces fit environmental screening, planning, real estate, utilities, conservation or research.',
		'Everything here runs live. The maps are served from PostGIS, not screenshots, and every model has a methods page showing exactly how it is calculated.'
	],

	services: [
		{
			title: 'Geospatial modeling and analysis',
			body: 'Suitability and risk models, spatial statistics and derived features in R and Python: land suitability, wildfire fuel hazard, flood and sea level rise exposure, terrain, soils, habitat and census analysis. Documented methods, delivered as layers you can map, query and report on.'
		},
		{
			title: 'Cartography and interactive maps',
			body: 'Web maps that follow cartographic conventions (standard wetland colours, hatched easements, flood-zone symbology) and stay fast at statewide scale: MapLibre and Svelte, vector tiles from PostGIS, cloud-optimized rasters, reusable map designs.'
		},
		{
			title: 'Custom reporting',
			body: 'Reports and dashboards from the same data: D3 charts for any area on the fly, per-parcel and per-town analysis reports, printable PDF reports, and methods pages that explain every number.'
		},
		{
			title: 'Data engineering and spatial databases',
			body: 'Repeatable pipelines from the Maine GeoLibrary, USGS, Census, USDA, FEMA, LANDFIRE, NOAA and Overture Maps into PostGIS, with provenance and health checks; schema design, published views, least-privilege roles, and cloud deployment on AWS.'
		}
	],

	stack: ['R', 'Python', 'PostGIS', 'SvelteKit', 'MapLibre', 'D3', 'tipg (OGC API)', 'TiTiler', 'GDAL', 'FastAPI', 'Docker', 'AWS (EC2, S3)', 'Playwright'],

	/** Landing banner photo (frontend/static/) and its credit. Empty image = the plain dark banner. */
	hero: {
		image: '/hero-bold-coast.jpg',
		/** Where the visible part sits when the banner is wider or narrower than the photo (CSS background-position). */
		position: 'center 15%',
		credit: "Bold Coast, Downeast Maine · New England Wilderness Trust",
		creditUrl: 'https://newildernesstrust.org/conservation-collaboration-bold-coast/'
	},

	/** Published projects with this tag are featured on the landing page (up to three, in catalogue order). */
	featuredTag: 'featured',

	contact: {
		email: 'rwspatial@gmail.com',
		/** Shown as written; the link dials the digits (US numbers get +1). */
		phone: '(207) 266-1634',
		github: '',
		linkedin: '',
		/** e.g. a scheduling link */
		booking: ''
	}
};

/** Page title helper: "Maine Coast · Downeast Geospatial". */
export const title = (...parts: string[]) => [...parts, site.studio].join(' · ');
