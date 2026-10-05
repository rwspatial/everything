// The town vulnerability assessment (process py.town_vulnerability, docs/methods/town-vulnerability.json): the shape
// of its report and helpers shared by the workspace view and the printable /p/<slug>/assessment page.

export interface Scenario {
	id: string;
	label: string;
	source: string;
	horizon: string;
	note: string;
	acres_direct: number;
	acres_barrier: number;
	present: boolean;
}
export interface Exposure {
	asset: string;
	unit: 'count' | 'miles';
	total: number;
	sub?: boolean;
	named?: boolean;
	by: Record<string, { direct: number; barrier: number }>;
}
export interface Asset {
	kind: string;
	name: string;
	detail: string | null;
	condition: string | null;
	criticality: number;
	first: string;
	connection: 'direct' | 'barrier';
	scenarios: Record<string, 'direct' | 'barrier'>;
	tier: 'High' | 'Medium' | 'Low';
	score: number;
	lon: number;
	lat: number;
}
export interface Tract {
	geoid: string;
	name: string;
	share: number | null;
	svi: number | null;
	svi_socioeconomic: number | null;
	svi_household: number | null;
	svi_minority: number | null;
	svi_housing_transport: number | null;
	pct_65_over: number | null;
	pct_no_vehicle: number | null;
	pct_disability: number | null;
	nri_risk: string | null;
	nri_social_vulnerability: string | null;
	nri_community_resilience: string | null;
}
export interface Action {
	horizon: 'Near-term' | 'Medium-term' | 'Longer-term';
	action: string;
	evidence: string;
	funding: string;
}
export interface Assessment {
	method: { id: string; version: number };
	town: { key: string; name: string; short_name: string; county: string; area_sqmi: number | null; pop: number | null; coastal: boolean };
	scenarios: Scenario[];
	exposure: Exposure[];
	roads_by_class: Record<string, Record<string, number>>;
	assets: Asset[];
	assets_total: number;
	people: {
		town: { pop?: number; median_age?: number; pct_65_plus?: number; poverty_pct?: number; median_hh_income?: number; pct_seasonal?: number; housing_units?: number };
		tracts: Tract[];
		nri_hazard_scores: Record<string, number>;
		settlements: { class: string; count: number; buildings: number; acres_in_1pct_flood: number }[];
	};
	actions: Action[];
}

export const TIER_COLORS: Record<string, string> = { High: '#b2182b', Medium: '#ef8a62', Low: '#fddbc7' };
export const HORIZONS = ['Near-term', 'Medium-term', 'Longer-term'] as const;
export const NRI_HAZARDS: Record<string, string> = {
	coastal_flood: 'Coastal flooding',
	inland_flood: 'Riverine (inland) flooding',
	hurricane: 'Hurricane',
	winter_weather: 'Winter weather',
	ice_storm: 'Ice storm'
};

const n0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const n1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
/** A count or miles; the behind-a-barrier part (if any) as "+N". */
export function cell(e: Exposure, scenario: string): { main: string; extra: string } {
	const v = e.by[scenario];
	const fmt = e.unit === 'miles' ? n1 : n0;
	if (!v) return { main: '–', extra: '' };
	return { main: v.direct ? fmt.format(v.direct) : '–', extra: v.barrier ? `+${fmt.format(v.barrier)}` : '' };
}
export const fmtTotal = (e: Exposure) => (e.unit === 'miles' ? `${n1.format(e.total)} mi` : n0.format(e.total));
export const pct = (v: number | null | undefined) => (v == null ? '–' : `${n0.format(v)} %`);
export const rank = (v: number | null | undefined) => (v == null ? '–' : v.toFixed(2));
