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

export interface Basemap {
	label: string;
	style: string | StyleSpecification;
}

export const basemaps: Record<string, Basemap> = {
	positron: { label: 'Light (OpenFreeMap)', style: 'https://tiles.openfreemap.org/styles/positron' },
	liberty: { label: 'Streets (OpenFreeMap)', style: 'https://tiles.openfreemap.org/styles/liberty' },
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
