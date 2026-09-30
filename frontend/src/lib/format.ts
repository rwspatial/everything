const nf = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

export function formatValue(v: unknown): string {
	if (v === null || v === undefined || v === '') return '–';
	if (typeof v === 'number') return nf.format(v);
	return String(v);
}

/** Fill "{field}" placeholders from feature properties. */
export function fillTemplate(template: string, props: Record<string, unknown>): string {
	return template.replace(/\{([^}]+)\}/g, (_, key: string) => formatValue(props[key.trim()]));
}

/** Distinct colours for layers without an explicit style (colour-blind-safe Okabe–Ito). */
export const PALETTE = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#56B4E9', '#882255'];
