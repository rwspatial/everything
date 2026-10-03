// Site identity: the one place to change names, copy and contact details.
// Empty strings are skipped on the page, so fill in only what you want public.

export const site = {
	/** Your name. When set, the landing page leads with it (for employers) and the studio becomes a subline. */
	person: '',
	/** Role shown next to your name. */
	role: 'Geospatial engineer',
	/** Practice / studio name, used in the header and page titles. */
	studio: 'Downeast Geospatial',
	location: 'Maine, USA',
	tagline: 'From raw public data to maps people can use: pipelines, spatial databases, tile services and web maps.',

	/** Draft copy; rewrite in your own voice. */
	about: [
		"I build the whole path from raw geospatial data to a map someone can act on: repeatable imports from state and federal sources, PostGIS databases, vector and raster tile services, and fast web viewers.",
		'Everything on this site runs on that stack. The maps are served live from PostGIS, not screenshots.'
	],

	services: [
		{
			title: 'Data pipelines',
			body: 'Repeatable imports from sources like the Maine GeoLibrary, USGS, Census, USDA, FEMA, NOAA and Overture Maps into PostGIS, with provenance, health checks and freshness tracking.'
		},
		{
			title: 'Web maps and tile services',
			body: 'Vector tiles straight from PostGIS, Cloud-Optimized GeoTIFFs through TiTiler, MapLibre viewers built for the people who use them, and printable PDF reports.'
		},
		{
			title: 'Spatial databases',
			body: 'PostGIS schema design, published views, least-privilege roles, migrations and query performance.'
		},
		{
			title: 'Spatial analysis',
			body: 'Hot spots and clusters, derived features like settlement outlines, and terrain, soils, habitat and census analysis in R and Python, with documented methods, delivered as layers you can map and query.'
		}
	],

	stack: ['PostGIS', 'tipg (OGC API)', 'TiTiler', 'GDAL / ogr2ogr', 'SvelteKit', 'MapLibre', 'R + Python', 'FastAPI', 'Playwright', 'Docker', 'Caddy'],

	/** Landing banner photo (frontend/static/) and its credit. Empty image = the plain dark banner. */
	hero: {
		image: '/hero-bold-coast.jpg',
		/** Where the visible part sits when the banner is wider or narrower than the photo (CSS background-position). */
		position: 'center 15%',
		credit: "Bold Coast, Downeast Maine · New England Wilderness Trust",
		creditUrl: 'https://newildernesstrust.org/conservation-collaboration-bold-coast/'
	},

	/** Projects with this tag are featured on the landing page as selected work. */
	featuredTag: 'maine',

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
