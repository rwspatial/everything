// Fill patterns for polygons (MapLibre `fill-pattern`), drawn on a canvas on demand like the route badges and POI
// icons, so no sprite sheet is needed. Ids name the pattern and its colour: `pat:<kind>:<rrggbb>`, e.g. `pat:diag:1b7837`.
// The kinds follow common GIS conventions: diagonal hatch for easements and floodways, cross-hatch for coastal high
// hazard, horizontal lines for waterfowl habitat, stipple for habitat blocks.
import type { Map as MlMap } from 'maplibre-gl';

export const PATTERN_KINDS = ['diag', 'back', 'cross', 'horiz', 'dots'] as const;
export type PatternKind = (typeof PATTERN_KINDS)[number];
const ID = /^pat:(diag|back|cross|horiz|dots):([0-9a-f]{6})$/;
const R = 2; // pixel ratio
const S = 10; // tile size, CSS px (the line spacing of the hatches)

/** The pattern tile as a canvas, or null for an id that is not a pattern. */
function draw(id: string): HTMLCanvasElement | null {
	const m = ID.exec(id);
	if (!m) return null;
	const kind = m[1] as PatternKind;
	const c = document.createElement('canvas');
	c.width = c.height = S * R;
	const g = c.getContext('2d')!;
	g.scale(R, R);
	g.strokeStyle = g.fillStyle = `#${m[2]}`;
	g.lineWidth = 1.2;
	g.lineCap = 'square';
	const line = (x1: number, y1: number, x2: number, y2: number) => {
		g.beginPath();
		g.moveTo(x1, y1);
		g.lineTo(x2, y2);
		g.stroke();
	};
	// Diagonals are drawn three times (offset by a tile) so they join seamlessly across tile edges.
	const diag = () => {
		for (const o of [-S, 0, S]) line(o, S, o + S, 0);
	};
	const back = () => {
		for (const o of [-S, 0, S]) line(o, 0, o + S, S);
	};
	if (kind === 'diag') diag();
	else if (kind === 'back') back();
	else if (kind === 'cross') {
		diag();
		back();
	} else if (kind === 'horiz') line(0, S / 2, S, S / 2);
	else {
		for (const [x, y] of [
			[S / 4, S / 4],
			[(3 * S) / 4, (3 * S) / 4]
		]) {
			g.beginPath();
			g.arc(x, y, 1.1, 0, Math.PI * 2);
			g.fill();
		}
	}
	return c;
}

/** Supplies a pattern image to the map when a style asks for it (from setMissingStyleImageResolver). */
export function providePattern(map: MlMap, id: string): void {
	if (map.hasImage(id)) return;
	const c = draw(id);
	if (c) map.addImage(id, c.getContext('2d')!.getImageData(0, 0, c.width, c.height), { pixelRatio: R });
}

/** The pattern as a CSS background (legend swatches), or '' for an unknown id. */
export function patternCss(id: string): string {
	const c = draw(id);
	return c ? `url(${c.toDataURL()}) 0 0 / ${S}px ${S}px` : '';
}
