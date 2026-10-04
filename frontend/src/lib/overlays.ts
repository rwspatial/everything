// Global overlays drawn on every map, above the project layers and outside the layer list.
// Roads: the basemap's own road lines (OpenMapTiles `transportation`) are lifted above the project layers, just below
// the labels, so a street name or route badge never floats over a hillshade or choropleth that hides its road. Basemaps
// without vector roads (aerials, "None") get the numbered routes drawn as lines instead. Maps that draw their own
// roads keep the basemap's roads underneath.
// Route badges: numbered routes (interstate, US, state) from pub.maine_transportation__route_shields, labelled along
// the road with a badge in the style of the road sign (US routes in the black-and-white shield). Badge images are
// drawn here on a canvas, so no sprite sheet is needed; they need glyphs (the offline "None" basemap has none).
import type { Map as MlMap } from 'maplibre-gl';
import { BADGE_FONT } from './basemaps';
import type { ProjectManifest } from './types';

export const isOverlayId = (id: string) => id.startsWith('o:');
/** Route line layers: project layers are drawn below them (they are the viewer's label anchor). */
export const isRoadOverlayId = (id: string) => id.startsWith('o:roads');
/** Basemap road layers lifted above the project layers, per map (reset on every style). */
const lifted = new WeakMap<MlMap, Set<string>>();
/** Road layers above the project layers (lifted basemap roads or route lines): project layers go below them. */
export const isRoadLayer = (map: MlMap, id: string) => isRoadOverlayId(id) || (lifted.get(map)?.has(id) ?? false);
const isBasemapLabel = (l: { id: string; type: string; metadata?: unknown }) =>
	!isOverlayId(l.id) && !l.id.startsWith('p:') && (l.type === 'symbol' || (l.metadata as Record<string, unknown> | undefined)?.['spatial:labels'] === true);

/** Moves the basemap's road lines (and bridges, rail) to just below its first label layer. Returns how many moved. */
function liftBasemapRoads(map: MlMap): number {
	const layers = map.getStyle().layers;
	const anchor = layers.find(isBasemapLabel)?.id;
	const roads = layers.filter((l) => !isOverlayId(l.id) && (l as { 'source-layer'?: string })['source-layer'] === 'transportation' && l.type !== 'symbol');
	for (const l of roads) map.moveLayer(l.id, anchor);
	lifted.set(map, new Set(roads.map((l) => l.id)));
	return roads.length;
}
/** Whether a project draws its own roads (then the route lines are left out). */
export const hasOwnRoads = (manifest: ProjectManifest) =>
	manifest.layers.some((l) => /__(public_)?roads/.test((l.source as { collection?: string }).collection ?? ''));
const SOURCE = 'o:route-shields';

type Kind = 'interstate' | 'us' | 'state';
const KINDS: { kind: Kind; minzoom: number; text: string }[] = [
	{ kind: 'interstate', minzoom: 6, text: '#ffffff' },
	{ kind: 'us', minzoom: 7, text: '#111111' },
	{ kind: 'state', minzoom: 9, text: '#111111' }
];

const R = 2; // pixel ratio of the badge images
const W = 26;
const H = 20;
/** US route shield widths by number of characters (the shield keeps its shape, so it does not stretch). */
const SHIELD_W = [0, 22, 25, 31];
const SHIELD_H = 24;

/** The US route marker: a white shield with a black outline (MUTCD M1-4). */
function usShield(chars: number): ImageData {
	const w = SHIELD_W[Math.min(Math.max(chars, 1), 3)];
	const h = SHIELD_H;
	const c = document.createElement('canvas');
	c.width = w * R;
	c.height = h * R;
	const g = c.getContext('2d')!;
	g.scale(R, R);
	const x = (f: number) => 1 + f * (w - 2);
	const y = (f: number) => 1 + f * (h - 2);
	g.beginPath();
	g.moveTo(x(0.5), y(0.1));
	g.quadraticCurveTo(x(0.36), y(-0.02), x(0.2), y(0.04)); // top edge dips in the middle, rises to the shoulders
	g.quadraticCurveTo(x(0.12), y(0.13), x(0.0), y(0.13)); // left ear
	g.bezierCurveTo(x(0.06), y(0.36), x(-0.02), y(0.72), x(0.5), y(1)); // flared side down to the point
	g.bezierCurveTo(x(1.02), y(0.72), x(0.94), y(0.36), x(1), y(0.13));
	g.quadraticCurveTo(x(0.88), y(0.13), x(0.8), y(0.04));
	g.quadraticCurveTo(x(0.64), y(-0.02), x(0.5), y(0.1));
	g.closePath();
	g.fillStyle = '#ffffff';
	g.fill();
	g.lineWidth = 1.6;
	g.lineJoin = 'round';
	g.strokeStyle = '#111111';
	g.stroke();
	return g.getImageData(0, 0, w * R, h * R);
}

/** A stretchable badge (icon-text-fit grows its middle to fit the number). */
function badge(kind: Kind): { data: ImageData; stretchX: [number, number][]; stretchY: [number, number][]; content: [number, number, number, number] } {
	const c = document.createElement('canvas');
	c.width = W * R;
	c.height = H * R;
	const g = c.getContext('2d')!;
	g.scale(R, R);
	const round = (x: number, y: number, w: number, h: number, r: number) => {
		g.beginPath();
		g.roundRect(x, y, w, h, r);
	};
	if (kind === 'interstate') {
		round(1, 1, W - 2, H - 2, 5);
		g.fillStyle = '#1f4e9c';
		g.fill();
		g.save();
		g.clip();
		g.fillStyle = '#c8102e';
		g.fillRect(0, 0, W, 5);
		g.restore();
		round(1, 1, W - 2, H - 2, 5);
		g.lineWidth = 1.5;
		g.strokeStyle = '#ffffff';
		g.stroke();
	} else {
		round(1, 1, W - 2, H - 2, kind === 'us' ? 3 : 9);
		g.fillStyle = '#ffffff';
		g.fill();
		g.lineWidth = kind === 'us' ? 2 : 1.4;
		g.strokeStyle = '#1b1b1b';
		g.stroke();
	}
	return {
		data: g.getImageData(0, 0, W * R, H * R),
		stretchX: [[9 * R, (W - 9) * R]],
		stretchY: [[8 * R, (H - 6) * R]],
		content: [5 * R, 5 * R, (W - 5) * R, (H - 3) * R]
	};
}

/** Supplies the badge images on demand (also after a basemap switch, which drops style images). */
export function provideBadge(map: MlMap, id: string): void {
	const us = /^badge-us-(\d)$/.exec(id);
	if (us) {
		if (!map.hasImage(id)) map.addImage(id, usShield(Number(us[1])), { pixelRatio: R });
		return;
	}
	const kind = id.replace(/^badge-/, '') as Kind;
	if (!KINDS.some((k) => k.kind === kind) || map.hasImage(id)) return;
	const b = badge(kind);
	map.addImage(id, b.data, { pixelRatio: R, stretchX: b.stretchX, stretchY: b.stretchY, content: b.content });
}

const ROAD_WIDTH = (scale: number) => ['interpolate', ['linear'], ['zoom'], 6, 0.6 * scale, 10, 1.6 * scale, 14, 4 * scale];
const ROAD_KINDS: { kind: Kind; minzoom: number; color: string; scale: number }[] = [
	{ kind: 'state', minzoom: 8, color: '#9a9184', scale: 0.8 },
	{ kind: 'us', minzoom: 6, color: '#7d7468', scale: 1 },
	{ kind: 'interstate', minzoom: 5, color: '#5e564c', scale: 1.25 }
];

/** Adds the route lines and badges to the current style (idempotent). Badges are skipped without glyphs. */
export function addOverlays(map: MlMap, tilesBase: string, { roads = true }: { roads?: boolean } = {}): void {
	if (map.getSource(SOURCE)) return;
	lifted.delete(map);
	const basemapRoads = roads ? liftBasemapRoads(map) : 0;
	map.addSource(SOURCE, {
		type: 'vector',
		tiles: [`${tilesBase}/collections/pub.maine_transportation__route_shields/tiles/WebMercatorQuad/{z}/{x}/{y}`],
		minzoom: 5,
		maxzoom: 14,
		attribution: 'Route numbers: MaineDOT'
	});
	if (roads && !basemapRoads) {
		// Below the first basemap label layer (place names stay on top); minor routes first, so major ones draw over.
		const before = map.getStyle().layers.find(isBasemapLabel)?.id;
		const casing = ROAD_KINDS.map(({ kind, minzoom, scale }) => ({
			id: `o:roads-${kind}-casing`,
			type: 'line' as const,
			source: SOURCE,
			'source-layer': 'default',
			minzoom,
			filter: ['==', ['get', 'kind'], kind],
			layout: { 'line-cap': 'round' as const, 'line-join': 'round' as const },
			paint: { 'line-color': '#ffffff', 'line-opacity': 0.85, 'line-width': ROAD_WIDTH(scale + 1.2) }
		}));
		const core = ROAD_KINDS.map(({ kind, minzoom, color, scale }) => ({
			id: `o:roads-${kind}`,
			type: 'line' as const,
			source: SOURCE,
			'source-layer': 'default',
			minzoom,
			filter: ['==', ['get', 'kind'], kind],
			layout: { 'line-cap': 'round' as const, 'line-join': 'round' as const },
			paint: { 'line-color': color, 'line-width': ROAD_WIDTH(scale) }
		}));
		for (const layer of [...casing, ...core]) map.addLayer(layer as never, before);
	}
	if (!map.getStyle().glyphs) return;
	// The OpenFreeMap basemaps draw their own small grey shields; ours replace them in Maine.
	for (const l of map.getStyle().layers) {
		if (!isOverlayId(l.id) && /shield/i.test(l.id)) map.setLayoutProperty(l.id, 'visibility', 'none');
	}
	// Labels are placed top layer first: add state routes first so interstates (added last, on top) win collisions.
	for (const { kind, minzoom, text } of [...KINDS].reverse()) {
		map.addLayer({
			id: `o:route-shields-${kind}`,
			type: 'symbol',
			source: SOURCE,
			'source-layer': 'default',
			minzoom,
			filter: ['==', ['get', 'kind'], kind],
			layout: {
				'symbol-placement': 'line',
				'symbol-spacing': kind === 'state' ? 320 : 420,
				'symbol-sort-key': ['get', 'rank'],
				'text-field': ['get', 'ref'],
				'text-font': BADGE_FONT,
				'text-size': kind === 'state' ? 10 : 11,
				'text-rotation-alignment': 'viewport',
				'text-pitch-alignment': 'viewport',
				...(kind === 'us'
					? {
							// Fixed-shape shield picked by the number's length; the number sits a little high, in the shield's body.
							'icon-image': ['concat', 'badge-us-', ['to-string', ['min', 3, ['length', ['get', 'ref']]]]],
							'text-offset': [0, -0.15]
						}
					: { 'icon-image': `badge-${kind}`, 'icon-text-fit': 'both', 'icon-text-fit-padding': [1, 2, 1, 2] }),
				'icon-rotation-alignment': 'viewport',
				'icon-pitch-alignment': 'viewport',
				'text-padding': 6
			},
			paint: { 'text-color': text }
		});
	}
}
