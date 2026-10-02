// Style presets for the project creator (plan Phase 3, deliverable 4). Each preset turns a field and
// its statistics (from /api/admin/projects/stats) into MapLibre style fragments plus a legend, i.e. the
// same `style` / `legend` a hand-written manifest has. Breaks are quantiles computed in PostGIS.
import type { LegendSpec, StyleFragment, StyleSpec } from './types';

export type Preset = 'single' | 'categorical' | 'choropleth' | 'graduated-circle' | 'heatmap';
export type GeomKind = 'polygon' | 'line' | 'point';

export const PRESET_LABELS: Record<Preset, string> = {
	single: 'Single colour',
	categorical: 'Categories (one colour per value)',
	choropleth: 'Classed colours (quantiles of a number)',
	'graduated-circle': 'Circles sized by a number',
	heatmap: 'Heatmap (point density)'
};

/** Presets that need a field, and whether it must be numeric. */
export const PRESET_FIELD: Record<Preset, 'none' | 'any' | 'numeric' | 'optional-numeric'> = {
	single: 'none',
	categorical: 'any',
	choropleth: 'numeric',
	'graduated-circle': 'numeric',
	heatmap: 'optional-numeric'
};

export const SEQUENTIAL = ['#f1eef6', '#bdc9e1', '#74a9cf', '#2b8cbe', '#045a8d'];
export const CATEGORICAL = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9', '#882255', '#44AA99', '#999933', '#AA4499'];
export const NO_DATA = '#d9d9d9';
const OTHER = '#bdbdbd';

export interface NumericStats {
	kind: 'numeric';
	min: number | null;
	max: number | null;
	breaks: number[] | null;
}
export interface CategoryStats {
	kind: 'categorical';
	values: { value: string | null; count: number }[];
	more: boolean;
}
export type FieldStats = NumericStats | CategoryStats;

export function geomKind(geometry: string | null | undefined): GeomKind {
	const g = (geometry ?? '').toLowerCase();
	return g.includes('polygon') ? 'polygon' : g.includes('line') ? 'line' : 'point';
}

export function presetsFor(g: GeomKind): Preset[] {
	return g === 'point'
		? ['single', 'categorical', 'choropleth', 'graduated-circle', 'heatmap']
		: ['single', 'categorical', 'choropleth'];
}

const num = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });
const short = (n: number) => num.format(Math.abs(n) >= 1000 ? Math.round(n / 100) * 100 : n);

// Expressions are plain JSON here; MapLibre's own types for them are stricter than we need to be.
type Expr = unknown;

function fragments(g: GeomKind, color: Expr): StyleFragment[] {
	const f =
		g === 'polygon'
			? [
					{ type: 'fill', paint: { 'fill-color': color, 'fill-opacity': 0.75 } },
					{ type: 'line', paint: { 'line-color': '#ffffff', 'line-width': 0.4 } }
				]
			: g === 'line'
				? [{ type: 'line', paint: { 'line-color': color, 'line-width': 1.6 } }]
				: [{ type: 'circle', paint: { 'circle-color': color, 'circle-radius': 4.5, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1 } }];
	return f as unknown as StyleFragment[];
}

export interface BuiltStyle {
	style: StyleSpec;
	legend: LegendSpec;
}

export function buildStyle(preset: Preset, g: GeomKind, field: string | null, stats: FieldStats | null, color: string, label: string): BuiltStyle {
	const wrap = (layers: StyleFragment[], legend: LegendSpec): BuiltStyle => ({ style: { kind: 'maplibre', layers }, legend });
	const single = () => wrap(fragments(g, color), { type: 'single', color, label });

	if (preset === 'categorical' && field && stats?.kind === 'categorical') {
		const values = stats.values.filter((v) => v.value !== null).slice(0, CATEGORICAL.length);
		if (!values.length) return single();
		const match: Expr[] = ['match', ['to-string', ['get', field]]];
		values.forEach((v, i) => match.push(v.value, CATEGORICAL[i]));
		match.push(OTHER);
		const items = values.map((v, i) => ({ label: String(v.value), color: CATEGORICAL[i] }));
		if (stats.more || stats.values.some((v) => v.value === null)) items.push({ label: 'Other', color: OTHER });
		return wrap(fragments(g, match), { type: 'categorical', title: field, items });
	}

	if (preset === 'choropleth' && field && stats?.kind === 'numeric' && stats.breaks?.length) {
		const breaks = [...new Set(stats.breaks)].sort((a, b) => a - b);
		const colors = SEQUENTIAL.slice(SEQUENTIAL.length - breaks.length - 1);
		const step: Expr[] = ['step', ['to-number', ['get', field]], colors[0]];
		breaks.forEach((b, i) => step.push(b, colors[i + 1]));
		const expr = ['case', ['==', ['get', field], null], NO_DATA, step];
		const items = colors.map((c, i) => ({
			color: c,
			label: i === 0 ? `under ${short(breaks[0])}` : i === breaks.length ? `${short(breaks[i - 1])} and over` : `${short(breaks[i - 1])}–${short(breaks[i])}`
		}));
		items.push({ label: 'no data', color: NO_DATA });
		return wrap(fragments(g, expr), { type: 'categorical', title: `${field} (quantiles)`, items });
	}

	if (preset === 'graduated-circle' && field && stats?.kind === 'numeric' && stats.min !== null && stats.max !== null && stats.max > stats.min) {
		const layer = {
			type: 'circle',
			paint: {
				'circle-color': color,
				'circle-opacity': 0.8,
				'circle-radius': ['interpolate', ['linear'], ['to-number', ['get', field], 0], stats.min, 3, stats.max, 16],
				'circle-stroke-color': '#ffffff',
				'circle-stroke-width': 1
			}
		};
		return wrap([layer as unknown as StyleFragment], { type: 'single', color, label: `${label} (size = ${field})` });
	}

	if (preset === 'heatmap') {
		const weight =
			field && stats?.kind === 'numeric' && stats.min !== null && stats.max !== null && stats.max > stats.min
				? ['interpolate', ['linear'], ['to-number', ['get', field], 0], stats.min, 0, stats.max, 1]
				: 1;
		const layer = { type: 'heatmap', paint: { 'heatmap-weight': weight, 'heatmap-radius': 14, 'heatmap-opacity': 0.8 } };
		return wrap([layer as unknown as StyleFragment], {
			type: 'gradient',
			title: field ? `Density weighted by ${field}` : 'Point density',
			stops: [
				{ value: 'low', color: '#67a9cf' },
				{ value: 'high', color: '#b2182b' }
			]
		});
	}

	return single();
}
