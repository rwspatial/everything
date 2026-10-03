// Basemap registry, keyed by the manifest's view.basemap.
// Internet basemaps fall back to a plain background when unreachable, so project layers
// still render offline.
import type { StyleSpecification } from 'maplibre-gl';

const blank: StyleSpecification = {
	version: 8,
	sources: {},
	layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#eef1f4' } }]
};

const osmRaster: StyleSpecification = {
	version: 8,
	sources: {
		osm: {
			type: 'raster',
			tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
			tileSize: 256,
			maxzoom: 19,
			attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
		}
	},
	layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
};

/** Marks a basemap layer as a label overlay: project layers are drawn below it (see Viewer). */
export const LABELS_METADATA = { 'spatial:labels': true };

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const esriAttribution =
	'Imagery © <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics, and the GIS User Community';

function aerial(withLabels: boolean): StyleSpecification {
	return {
		version: 8,
		sources: {
			imagery: {
				type: 'raster',
				tiles: [`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`],
				tileSize: 256,
				maxzoom: 19,
				attribution: esriAttribution
			},
			...(withLabels
				? {
						labels: {
							type: 'raster' as const,
							tiles: [`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`],
							tileSize: 256,
							maxzoom: 19,
							attribution: 'Boundaries and places © Esri'
						}
					}
				: {})
		},
		layers: [
			{ id: 'imagery', type: 'raster', source: 'imagery' },
			...(withLabels ? [{ id: 'labels', type: 'raster' as const, source: 'labels', metadata: LABELS_METADATA }] : [])
		]
	};
}

// USDA NAIP (60 cm to 1 m, leaf-on, latest statewide collection) from The National Map's image service. It is not
// cached as tiles, so each 256 px tile is an exportImage request for that tile's Web Mercator box (about 1–2 s each).
const NAIP =
	'https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage' +
	'?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpgpng&f=image';

function naip(withLabels: boolean): StyleSpecification {
	const base = aerial(withLabels);
	return {
		...base,
		sources: {
			...base.sources,
			imagery: { type: 'raster', tiles: [NAIP], tileSize: 256, maxzoom: 18, attribution: 'NAIP imagery: USDA Farm Production and Conservation, via USGS The National Map' }
		}
	};
}

export interface Basemap {
	label: string;
	style: string | StyleSpecification;
}

export const basemaps: Record<string, Basemap> = {
	positron: { label: 'Light (OpenFreeMap)', style: 'https://tiles.openfreemap.org/styles/positron' },
	liberty: { label: 'Streets (OpenFreeMap)', style: 'https://tiles.openfreemap.org/styles/liberty' },
	'aerial-labels': { label: 'Aerial + labels (Esri)', style: aerial(true) },
	aerial: { label: 'Aerial (Esri)', style: aerial(false) },
	'naip-labels': { label: 'NAIP aerial + labels (USDA)', style: naip(true) },
	naip: { label: 'NAIP aerial (USDA)', style: naip(false) },
	'osm-raster': { label: 'OpenStreetMap (raster)', style: osmRaster },
	none: { label: 'None (works offline)', style: blank }
};

export const DEFAULT_BASEMAP = 'positron';

/** Resolve a basemap to a style object; `fallback` is true when the online style was unreachable. */
export async function resolveBasemap(key: string | undefined): Promise<{ key: string; style: StyleSpecification; fallback: boolean }> {
	const k = key && key in basemaps ? key : DEFAULT_BASEMAP;
	const { style } = basemaps[k];
	if (typeof style !== 'string') return { key: k, style, fallback: false };
	try {
		const ctrl = new AbortController();
		const timer = setTimeout(() => ctrl.abort(), 6000);
		const res = await fetch(style, { signal: ctrl.signal });
		clearTimeout(timer);
		if (!res.ok) throw new Error(String(res.status));
		return { key: k, style: (await res.json()) as StyleSpecification, fallback: false };
	} catch {
		return { key: k, style: blank, fallback: true };
	}
}
