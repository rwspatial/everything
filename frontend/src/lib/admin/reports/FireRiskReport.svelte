<script lang="ts">
	// Report of py.fire_risk (docs/methods/fire-risk.json).
	import type { AnalysisRun } from '../api';
	import ScoreHeader from './ScoreHeader.svelte';

	let { run }: { run: AnalysisRun } = $props();
	interface Fuel { fuel_model: string; fuel_name: string; acres: number; hazard: number; class: string; spread: string | null; flame: string | null }
	interface Fire {
		score: number;
		class: string;
		parcel: { acres: number };
		on_parcel: number;
		surroundings: number;
		weights: { parcel: number; surroundings: number };
		acres_by_class: Record<string, number>;
		fuels: Fuel[];
		surrounding_fuels: { fuel_model: string; fuel_name: string; pct: number; hazard: number }[];
		burnable_pct: number;
		buildings: number;
		buildings_near_high_hazard: number;
		slope_deg: { max: number; mean: number } | null;
	}
	const r = $derived(run.report as unknown as Fire);
	const COLORS: Record<string, string> = { 'Very high': '#b30000', High: '#e34a33', Moderate: '#fc8d59', Low: '#fdcc8a', 'Very low': '#fef0d9', 'Non-burnable': '#d9d9d9' };
	const ORDER = ['Very high', 'High', 'Moderate', 'Low', 'Very low', 'Non-burnable'];
	const n1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
</script>

<div class="report" aria-label="Latest result">
	<ScoreHeader score={r.score} cls={r.class} what="wildfire fuel hazard" acres={r.parcel.acres} finished={run.finished_at} order={ORDER} colors={COLORS} byClass={r.acres_by_class} />

	<h4>Where the score comes from <span class="hint">(0–100; weight in brackets)</span></h4>
	<ul class="bars" style:--bar="#e34a33">
		<li>
			<span class="lbl">Fuels on the parcel <span class="hint">({Math.round(r.weights.parcel * 100)} %)</span></span>
			<span class="track"><span class="fill" style:width="{r.on_parcel}%"></span></span>
			<span class="val">{r.on_parcel}</span>
		</li>
		<li>
			<span class="lbl">Fuels within 500 m <span class="hint">({Math.round(r.weights.surroundings * 100)} %)</span></span>
			<span class="track"><span class="fill" style:width="{r.surroundings}%"></span></span>
			<span class="val">{r.surroundings}</span>
		</li>
	</ul>

	<h4>Fuels on the parcel <span class="hint">(LANDFIRE fuel models)</span></h4>
	<div class="table-wrap">
		<table>
			<thead><tr><th>Fuel</th><th>Acres</th><th>Hazard</th><th>Spread / flames</th></tr></thead>
			<tbody>
				{#each r.fuels as f, i (i)}
					<tr>
						<td><strong>{f.fuel_model}</strong> {f.fuel_name}</td>
						<td class="num">{n1.format(f.acres)}</td>
						<td class="num"><i class="dot" style:background={COLORS[f.class]}></i>{f.hazard}</td>
						<td>{f.spread ? `${f.spread} / ${f.flame}` : 'does not burn'}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	<h4>Exposure</h4>
	<dl class="facts">
		<dt>Buildings</dt><dd>{r.buildings} on the parcel; {r.buildings_near_high_hazard} within 100 ft of high-hazard fuel</dd>
		<dt>Burnable</dt><dd>{n1.format(r.burnable_pct)} % of the parcel</dd>
		{#if r.slope_deg}<dt>Slope</dt><dd>{r.slope_deg.mean}° on average, up to {r.slope_deg.max}°</dd>{/if}
	</dl>
	{#if r.surrounding_fuels.length}
		<p class="hint">Within 500 m: {r.surrounding_fuels.slice(0, 4).map((f) => `${f.fuel_model} ${f.fuel_name.toLowerCase()} ${n1.format(f.pct)} %`).join(' · ')}</p>
	{/if}
	<p class="hint">A fuel hazard, not a probability of fire: weather, ignitions and fire history are not included.</p>
</div>
