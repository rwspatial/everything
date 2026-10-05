<script lang="ts">
	// Assets x hazard scenarios (py.town_vulnerability): counts (or miles) in tidally connected / FEMA areas, with the
	// part reached only behind a barrier (low-lying, not tidally connected) as "+N".
	import { cell, fmtTotal, type Assessment } from '$lib/assessment';

	let { a, compact = false }: { a: Assessment; compact?: boolean } = $props();
	const scen = $derived(a.scenarios.filter((s) => s.present));
	const rows = $derived(compact ? a.exposure.filter((e) => !e.named || Object.keys(e.by).length) : a.exposure);
</script>

<div class="table-wrap">
	<table class="exposure">
		<caption class="visually-hidden">Assets in each hazard scenario</caption>
		<thead>
			<tr>
				<th scope="col">Asset</th>
				<th scope="col" class="num">In town</th>
				{#each scen as s (s.id)}<th scope="col" class="num" title={s.note}>{s.label}<br /><span class="h">{s.horizon}</span></th>{/each}
			</tr>
		</thead>
		<tbody>
			{#each rows as e (e.asset)}
				<tr class:sub={e.sub}>
					<th scope="row">{e.asset}</th>
					<td class="num">{fmtTotal(e)}</td>
					{#each scen as s (s.id)}
						{@const c = cell(e, s.id)}
						<td class="num">{c.main}{#if c.extra}<span class="barrier" title="behind a barrier (not tidally connected)"> {c.extra}</span>{/if}</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
<p class="note">Counts touch the scenario; road figures are miles inside it. "+N": reached only behind a barrier (a low-lying area not tidally connected), flooded if it fails or is overtopped.</p>

<style>
	.exposure th[scope='row'] { font-weight: 500; white-space: nowrap; text-align: left; }
	.exposure thead th { white-space: normal; min-width: 4.5rem; }
	.exposure .h { font-weight: 400; text-transform: none; letter-spacing: 0; }
	.exposure tr.sub th { padding-left: 1.2rem; font-weight: 400; color: var(--muted, #5b6670); }
	.barrier { color: var(--muted, #5b6670); font-size: 0.85em; }
	.note { font-size: 0.75rem; color: var(--muted, #5b6670); margin: 0.3rem 0 0; }
</style>
