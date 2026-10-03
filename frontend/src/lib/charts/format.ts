// Number formats for charts (ChartSpec.format) and the palette they draw with.
import type { ChartFormat } from '$lib/contracts.gen';

const n0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const n1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const moneyCompact = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 });

/** Full value (tooltips, tables, stat tiles). */
export function fmt(v: number | null | undefined, f: ChartFormat = 'number'): string {
	if (v === null || v === undefined || Number.isNaN(v)) return '–';
	switch (f) {
		case 'currency': return money.format(v);
		case 'percent': return `${n1.format(v)}%`;
		case 'acres': return `${n0.format(v)} acres`;
		case 'sqmi': return `${n1.format(v)} sq mi`;
		case 'years': return `${n1.format(v)} years`;
		case 'mw': return `${n1.format(v)} MW`;
		case 'count': return n0.format(v);
		default: return Math.abs(v) >= 100 ? n0.format(v) : n1.format(v);
	}
}

/** Short value (axis ticks, bar-end labels). */
export function fmtShort(v: number, f: ChartFormat = 'number'): string {
	if (f === 'currency') return Math.abs(v) >= 10000 ? moneyCompact.format(v) : money.format(v);
	if (f === 'percent') return `${n0.format(v)}%`;
	if (f === 'mw') return `${compact.format(v)} MW`;
	return Math.abs(v) >= 10000 ? compact.format(v) : fmt(v, f === 'acres' || f === 'sqmi' || f === 'years' ? 'number' : f);
}

// Categorical palette in fixed order (dataviz reference palette, light mode; validated: adjacent CVD ΔE ≥ 9.1).
// Three slots sit below 3:1 on white, so every chart ships visible labels and a table view.
export const CATEGORICAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'];
export const SERIES = CATEGORICAL[0];
export const OTHER = '#a3a8ae';
