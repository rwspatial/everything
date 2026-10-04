// Point-of-interest icons for every map: a white Maki pictogram (CC0, @mapbox/maki) on a disc in the layer's colour.
// Layers ask for them by image id `poi:<icon>:<hex colour>` (e.g. "poi:school:9467bd", data-driven through a `match`
// expression), so one icon serves any colour and legends keep the colours they already show. The pictograms are
// rasterized once (loadIcons) so a missing image can be drawn synchronously, also after a basemap switch.
import type { Map as MlMap } from 'maplibre-gl';
import i0 from '@mapbox/maki/icons/school.svg?raw';
import i1 from '@mapbox/maki/icons/college.svg?raw';
import i2 from '@mapbox/maki/icons/hospital.svg?raw';
import i3 from '@mapbox/maki/icons/residential-community.svg?raw';
import i4 from '@mapbox/maki/icons/fire-station.svg?raw';
import i5 from '@mapbox/maki/icons/police.svg?raw';
import i6 from '@mapbox/maki/icons/shelter.svg?raw';
import i7 from '@mapbox/maki/icons/communications-tower.svg?raw';
import i8 from '@mapbox/maki/icons/dam.svg?raw';
import i9 from '@mapbox/maki/icons/airport.svg?raw';
import i10 from '@mapbox/maki/icons/heliport.svg?raw';
import i11 from '@mapbox/maki/icons/harbor.svg?raw';
import i12 from '@mapbox/maki/icons/bridge.svg?raw';
import i13 from '@mapbox/maki/icons/water.svg?raw';
import i14 from '@mapbox/maki/icons/car.svg?raw';
import i15 from '@mapbox/maki/icons/rail.svg?raw';
import i16 from '@mapbox/maki/icons/windmill.svg?raw';
import i17 from '@mapbox/maki/icons/slipway.svg?raw';

const SVG: Record<string, string> = {
	'school': i0,
	'college': i1,
	'hospital': i2,
	'residential-community': i3,
	'fire-station': i4,
	'police': i5,
	'shelter': i6,
	'communications-tower': i7,
	'dam': i8,
	'airport': i9,
	'heliport': i10,
	'harbor': i11,
	'bridge': i12,
	'water': i13,
	'car': i14,
	'rail': i15,
	'windmill': i16,
	'slipway': i17,
};

const R = 2; // pixel ratio
const SIZE = 26; // disc diameter + border, CSS px
const GLYPH = 14;
const glyphs = new Map<string, ImageBitmap>();
let loading: Promise<void> | null = null;

/** Rasterizes every pictogram in white (once per page). */
export function loadIcons(): Promise<void> {
	loading ??= Promise.all(
		Object.entries(SVG).map(async ([name, svg]) => {
			const white = svg.replace('<svg', '<svg fill="#ffffff"').replace(/width="\d+"/, `width="${GLYPH * R}"`).replace(/height="\d+"/, `height="${GLYPH * R}"`);
			const img = new Image();
			img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(white)}`;
			await img.decode();
			glyphs.set(name, await createImageBitmap(img, { resizeWidth: GLYPH * R, resizeHeight: GLYPH * R }));
		})
	).then(() => undefined);
	return loading;
}

/** Draws `poi:<icon>:<hex>` on demand (styleimagemissing). Unknown ids are left to other providers. */
export function providePoiIcon(map: MlMap, id: string): void {
	const m = /^poi:([a-z-]+):([0-9a-f]{6})$/.exec(id);
	const glyph = m && glyphs.get(m[1]);
	if (!m || !glyph || map.hasImage(id)) return;
	const c = document.createElement('canvas');
	c.width = c.height = SIZE * R;
	const g = c.getContext('2d')!;
	g.scale(R, R);
	g.beginPath();
	g.arc(SIZE / 2, SIZE / 2, SIZE / 2 - 1.2, 0, Math.PI * 2);
	g.fillStyle = `#${m[2]}`;
	g.fill();
	g.lineWidth = 1.6;
	g.strokeStyle = '#ffffff';
	g.stroke();
	g.drawImage(glyph, (SIZE - GLYPH) / 2, (SIZE - GLYPH) / 2, GLYPH, GLYPH);
	map.addImage(id, g.getImageData(0, 0, SIZE * R, SIZE * R), { pixelRatio: R });
}
