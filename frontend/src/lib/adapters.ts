// Layer adapter registry: the extension seam of the viewer (plan §2.2).
// Each LayerSpec.source.type maps to exactly one adapter that turns the spec into a
// MapLibre source + layers. New data (e.g. Phase 5 ML outputs) arrives as LayerSpecs of
// these types, so the UI does not change. Adding a type = adding one entry here.
import type { LayerSpecification, SourceSpecification } from 'maplibre-gl';
import type { LayerSpec, SourceSpec, SourceType, StyleFragment } from './types';

export interface AdapterContext {
	tilesBase: string;
	/** Current values for tiPG function arguments (from UI controls), overriding source.params. */
	params?: Record<string, string | number>;
	/** Fallback colour for layers without an explicit style. */
	color: string;
}

export interface MapLibreParts {
	sourceId: string;
	source: SourceSpecification;
	layers: LayerSpecification[];
}

type Adapter<T extends SourceType> = (
	spec: LayerSpec & { source: Extract<SourceSpec, { type: T }> },
	ctx: AdapterContext
) => MapLibreParts;

/** tiPG 1.6 names every tile layer "default" with TIPG_SET_MVT_LAYERNAME=FALSE (ADR 0002). */
const TIPG_SOURCE_LAYER = 'default';

export const sourceIdFor = (layerId: string) => `p:${layerId}`;
export const isProjectId = (id: string) => id.startsWith('p:');

function query(src: { properties?: string[]; params?: Record<string, string | number> }, ctx: AdapterContext, extra: Record<string, string> = {}) {
	const q = new URLSearchParams(extra);
	if (src.properties?.length) q.set('properties', src.properties.join(','));
	for (const [k, v] of Object.entries({ ...src.params, ...ctx.params })) q.set(k, String(v));
	const s = q.toString();
	return s ? `?${s}` : '';
}

export function tipgTileUrl(src: Extract<SourceSpec, { type: 'tipg-vector' }>, ctx: AdapterContext): string {
	const tms = src.tms ?? 'WebMercatorQuad';
	return `${ctx.tilesBase}/collections/${src.collection}/tiles/${tms}/{z}/{x}/{y}${query(src, ctx)}`;
}

const ANY = (types: string[]) => ['in', ['geometry-type'], ['literal', types]] as const;

/** Styling for layers that don't define one: polygons, lines and points in one colour. */
export function defaultFragments(color: string): StyleFragment[] {
	return [
		{ type: 'fill', filter: ANY(['Polygon', 'MultiPolygon']) as never, paint: { 'fill-color': color, 'fill-opacity': 0.35 } },
		{ type: 'line', filter: ANY(['LineString', 'MultiLineString', 'Polygon', 'MultiPolygon']) as never, paint: { 'line-color': color, 'line-width': 1.2 } },
		{
			type: 'circle',
			filter: ANY(['Point', 'MultiPoint']) as never,
			paint: { 'circle-color': color, 'circle-radius': 4, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1 }
		}
	];
}

export function fragmentsFor(spec: LayerSpec, ctx: AdapterContext): StyleFragment[] {
	if (spec.style?.layers?.length) return spec.style.layers;
	if (spec.source.type === 'raster-xyz') return [{ type: 'raster' }];
	return defaultFragments(ctx.color);
}

function layersFor(spec: LayerSpec, ctx: AdapterContext, sourceId: string, sourceLayer?: string): LayerSpecification[] {
	const visibility = spec.visible === false ? 'none' : 'visible';
	return fragmentsFor(spec, ctx).map((f, i) => {
		const layer: Record<string, unknown> = {
			...f,
			id: `${sourceId}:${i}`,
			source: sourceId,
			layout: { ...(('layout' in f && f.layout) || {}), visibility }
		};
		if (sourceLayer) layer['source-layer'] = sourceLayer;
		if (spec.minzoom !== undefined) layer.minzoom = spec.minzoom;
		if (spec.maxzoom !== undefined) layer.maxzoom = spec.maxzoom;
		return layer as unknown as LayerSpecification;
	});
}

const tipgVector: Adapter<'tipg-vector'> = (spec, ctx) => {
	const sourceId = sourceIdFor(spec.id);
	return {
		sourceId,
		source: {
			type: 'vector',
			tiles: [tipgTileUrl(spec.source, ctx)],
			maxzoom: spec.source.maxzoom ?? 16,
			...(spec.attribution ? { attribution: spec.attribution } : {})
		},
		layers: layersFor(spec, ctx, sourceId, TIPG_SOURCE_LAYER)
	};
};

const tipgGeojson: Adapter<'tipg-geojson'> = (spec, ctx) => {
	const sourceId = sourceIdFor(spec.id);
	const url = `${ctx.tilesBase}/collections/${spec.source.collection}/items${query(spec.source, ctx, {
		f: 'geojson',
		limit: String(spec.source.limit ?? 10000)
	})}`;
	return {
		sourceId,
		source: { type: 'geojson', data: url, ...(spec.attribution ? { attribution: spec.attribution } : {}) },
		layers: layersFor(spec, ctx, sourceId)
	};
};

const geojsonUrl: Adapter<'geojson-url'> = (spec, ctx) => {
	const sourceId = sourceIdFor(spec.id);
	return {
		sourceId,
		source: { type: 'geojson', data: new URL(spec.source.url, window.location.origin).href },
		layers: layersFor(spec, ctx, sourceId)
	};
};

const rasterXyz: Adapter<'raster-xyz'> = (spec, ctx) => {
	const sourceId = sourceIdFor(spec.id);
	return {
		sourceId,
		source: {
			type: 'raster',
			tiles: spec.source.tiles.map((t) => (t.startsWith('/') ? window.location.origin + t : t)),
			tileSize: spec.source.tileSize ?? 256,
			maxzoom: spec.source.maxzoom ?? 19,
			...(spec.attribution ? { attribution: spec.attribution } : {})
		},
		layers: layersFor(spec, ctx, sourceId)
	};
};

const registry: { [T in SourceType]: Adapter<T> } = {
	'tipg-vector': tipgVector,
	'tipg-geojson': tipgGeojson,
	'geojson-url': geojsonUrl,
	'raster-xyz': rasterXyz
};

export const adapterTypes = Object.keys(registry) as string[];

export function toMapLibre(spec: LayerSpec, ctx: AdapterContext): MapLibreParts {
	const adapter = registry[spec.source.type] as Adapter<SourceType>;
	return adapter(spec as never, ctx);
}

/** Paint properties that carry opacity, per MapLibre layer type. */
export const OPACITY_PROPS: Record<string, string[]> = {
	fill: ['fill-opacity'],
	line: ['line-opacity'],
	circle: ['circle-opacity', 'circle-stroke-opacity'],
	raster: ['raster-opacity'],
	symbol: ['text-opacity', 'icon-opacity'],
	heatmap: ['heatmap-opacity'],
	'fill-extrusion': ['fill-extrusion-opacity']
};

/** Scale each fragment's own opacity by the layer opacity (expressions only restore at 100 %). */
export function opacityPaint(fragment: StyleFragment, opacity: number): [string, unknown][] {
	const paint = ('paint' in fragment && (fragment.paint as Record<string, unknown>)) || {};
	return (OPACITY_PROPS[fragment.type] ?? []).map((prop) => {
		const base = paint[prop];
		if (typeof base === 'number') return [prop, base * opacity];
		if (base === undefined) return [prop, opacity];
		return [prop, opacity === 1 ? base : opacity];
	});
}
