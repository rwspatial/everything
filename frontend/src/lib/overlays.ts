// Global overlays drawn on every map, above the project layers and outside the layer list.
// Route badges: numbered routes (interstate, US, state) from pub.maine_transportation__route_shields, labelled along
// the road with a badge in the style of the road sign. Badge images are drawn here on a canvas, so no sprite sheet
// is needed and they work over every basemap that has glyphs (the offline "None" basemap has none: no badges).
import type { Map as MlMap } from 'maplibre-gl';
import { BADGE_FONT } from './basemaps';

export const isOverlayId = (id: string) => id.startsWith('o:');
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
	const kind = id.replace(/^badge-/, '') as Kind;
	if (!KINDS.some((k) => k.kind === kind) || map.hasImage(id)) return;
	const b = badge(kind);
	map.addImage(id, b.data, { pixelRatio: R, stretchX: b.stretchX, stretchY: b.stretchY, content: b.content });
}

/** Adds the route badge overlay on top of the current style (idempotent; skipped without glyphs). */
export function addOverlays(map: MlMap, tilesBase: string): void {
	if (!map.getStyle().glyphs || map.getSource(SOURCE)) return;
	// The OpenFreeMap basemaps draw their own small grey shields; ours replace them in Maine.
	for (const l of map.getStyle().layers) {
		if (!isOverlayId(l.id) && /shield/i.test(l.id)) map.setLayoutProperty(l.id, 'visibility', 'none');
	}
	map.addSource(SOURCE, {
		type: 'vector',
		tiles: [`${tilesBase}/collections/pub.maine_transportation__route_shields/tiles/WebMercatorQuad/{z}/{x}/{y}`],
		minzoom: 5,
		maxzoom: 14,
		attribution: 'Route numbers: MaineDOT'
	});
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
				'icon-image': `badge-${kind}`,
				'icon-text-fit': 'both',
				'icon-text-fit-padding': [1, 2, 1, 2],
				'icon-rotation-alignment': 'viewport',
				'icon-pitch-alignment': 'viewport',
				'text-padding': 6
			},
			paint: { 'text-color': text }
		});
	}
}
