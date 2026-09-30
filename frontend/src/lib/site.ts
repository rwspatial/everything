// Site identity: the one place to change names, copy and contact details.
// Empty strings are skipped on the page, so fill in only what you want public.

export const site = {
	/** Your name. When set, the landing page leads with it (for employers) and the studio becomes a subline. */
	person: '',
	/** Role shown next to your name. */
	role: 'Geospatial engineer',
	/** Practice / studio name, used in the header and page titles. */
	studio: 'Bold Coast Geospatial',
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
			body: 'Repeatable imports from sources like the Maine GeoLibrary, USGS, Census and NOAA into PostGIS, with provenance, health checks and freshness tracking.'
		},
		{
			title: 'Web maps and tile services',
			body: 'Vector tiles straight from PostGIS, Cloud-Optimized GeoTIFFs through TiTiler, and MapLibre viewers built for the people who use them.'
		},
		{
			title: 'Spatial databases',
			body: 'PostGIS schema design, published views, least-privilege roles, migrations and query performance.'
		},
		{
			title: 'Spatial analysis',
			body: 'Terrain, land cover, habitat and census analysis in R and Python, delivered as layers you can map and query.'
		}
	],

	stack: ['PostGIS', 'tipg (OGC API)', 'TiTiler', 'GDAL / ogr2ogr', 'SvelteKit', 'MapLibre', 'R + Python', 'Docker', 'Caddy'],

	/** Projects with this tag are featured on the landing page as selected work. */
	featuredTag: 'maine',

	contact: {
		email: '',
		github: '',
		linkedin: '',
		/** e.g. a scheduling link */
		booking: ''
	}
};

/** Page title helper: "Maine Coast · Bold Coast Geospatial". */
export const title = (...parts: string[]) => [...parts, site.studio].join(' · ');
