<script lang="ts">
	// Report of py.agricultural_potential (docs/methods/agricultural-potential.json).
	import type { AnalysisRun } from '../api';
	import ScoreHeader from './ScoreHeader.svelte';

	let { run }: { run: AnalysisRun } = $props();
	interface Ag {
		score: number;
		class: string;
		parcel: { acres: number };
		acres_by_class: Record<string, number>;
		factors: Record<string, number | null>;
		weights: Record<string, number>;
		soils: { soil: string; acres: number; score: number; class: string; limits: string }[];
		land_use: { class: string; pct: number }[];
		farmed_pct: number;
		forest_pct: number;
		hardiness_zone: string | null;
		elevation_ft: { min: number; mean: number; max: number } | null;
		fema_flood_zone_pct: number;
		wetland_pct: number;
		slope_source: string;
	}
	const r = $derived(run.report as unknown as Ag);
	const COLORS: Record<string, string> = { High: '#006d2c', Good: '#31a354', Moderate: '#74c476', Limited: '#c7e9c0', Unsuitable: '#d9d9d9' };
	const ORDER = ['High', 'Good', 'Moderate', 'Limited', 'Unsuitable'];
	const FACTORS: Record<string, string> = { capability: 'Soil capability', farmland: 'Farmland class', slope: 'Slope', drainage: 'Drainage', water: 'Water storage' };
	const n1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
</script>

<div class="report" aria-label="Latest result">
	<ScoreHeader score={r.score} cls={r.class} what="agricultural potential" acres={r.parcel.acres} finished={run.finished_at} order={ORDER} colors={COLORS} byClass={r.acres_by_class} />

	<h4>Factors <span class="hint">(0–100, area-weighted; weight in brackets)</span></h4>
	<ul class="bars">
		{#each Object.entries(r.factors) as [k, v] (k)}
			<li>
				<span class="lbl">{FACTORS[k] ?? k} <span class="hint">({Math.round((r.weights[k] ?? 0) * 100)} %)</span></span>
				<span class="track"><span class="fill" style:width="{v ?? 0}%"></span></span>
				<span class="val">{v ?? 'n/a'}</span>
			</li>
		{/each}
	</ul>

	<h4>Soils on the parcel</h4>
	<div class="table-wrap">
		<table>
			<thead><tr><th>Soil</th><th>Acres</th><th>Score</th><th>Limits</th></tr></thead>
			<tbody>
				{#each r.soils as s, i (i)}
					<tr>
						<td>{s.soil}</td>
						<td class="num">{n1.format(s.acres)}</td>
						<td class="num"><i class="dot" style:background={COLORS[s.class]}></i>{s.score}</td>
						<td>{s.limits}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<h4>The land today</h4>
	<dl class="facts">
		<dt>Farmed now</dt><dd>{n1.format(r.farmed_pct)} % (crops, hay, pasture, orchards)</dd>
		<dt>Forest</dt><dd>{n1.format(r.forest_pct)} %</dd>
		<dt>Wetlands</dt><dd>{r.wetland_pct} % (NWI)</dd>
		<dt>FEMA flood zone</dt><dd>{n1.format(r.fema_flood_zone_pct)} %</dd>
		{#if r.hardiness_zone}<dt>Hardiness zone</dt><dd>{r.hardiness_zone}</dd>{/if}
		{#if r.elevation_ft}<dt>Elevation</dt><dd>{r.elevation_ft.min}–{r.elevation_ft.max} ft</dd>{/if}
		<dt>Slope from</dt><dd>{r.slope_source}</dd>
	</dl>
	{#if r.land_use.length}
		<p class="hint">Land cover (Cropland Data Layer 2025): {r.land_use.slice(0, 5).map((u) => `${u.class} ${n1.format(u.pct)} %`).join(' · ')}</p>
	{/if}
</div>
