<script lang="ts">
	// The top of a place-analysis report: the score with its class colour, and the parcel's acres by class.
	let {
		score,
		cls,
		what,
		acres,
		finished,
		order,
		colors,
		byClass
	}: {
		score: number;
		cls: string;
		what: string;
		acres: number;
		finished: string | null;
		order: string[];
		colors: Record<string, string>;
		byClass: Record<string, number>;
	} = $props();
	const n1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
	const when = (s: string | null) => (s ? new Date(s).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : '');
	const present = $derived(order.filter((c) => byClass[c]));
	const total = $derived(present.reduce((a, c) => a + byClass[c], 0) || 1);
</script>

<div class="score">
	<span class="big" style:--c={colors[cls]}>{score}</span>
	<div>
		<span><strong>{cls}</strong> {what}</span>
		<span class="hint">out of 100, area-weighted over {n1.format(acres)} acres · {when(finished)}</span>
	</div>
</div>

<h4>Acres by class</h4>
<div class="stack" role="img" aria-label={present.map((c) => `${c}: ${n1.format(byClass[c])} acres`).join(', ')}>
	{#each present as c (c)}<span style:width="{(100 * byClass[c]) / total}%" style:background={colors[c]} title="{c}: {n1.format(byClass[c])} acres"></span>{/each}
</div>
<ul class="legend">
	{#each present as c (c)}<li><i style:background={colors[c]}></i>{c} <span>{n1.format(byClass[c])} ac</span></li>{/each}
</ul>
