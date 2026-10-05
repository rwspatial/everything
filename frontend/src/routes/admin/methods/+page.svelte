<script lang="ts">
	import type { DatasetRow } from '$lib/admin/api';

	let { data } = $props();

	// Sources: every dataset that is loaded (has outputs), grouped by publisher, with the credit line its terms ask for.
	let q = $state('');
	const loaded = $derived(data.datasets.filter((d) => d.outputs_total > 0));
	const notLoaded = $derived(data.datasets.length - loaded.length);
	// One group per publisher: "U.S. Census Bureau (TIGER/Line)" and "(ACS)" are both the Census Bureau.
	const publisher = (d: DatasetRow) => d.agency?.replace(/\s*\([^)]*\)\s*$/, '').trim() || 'Other sources';
	const match = (d: DatasetRow, s: string) =>
		[d.title, d.agency, d.attribution, d.license, d.name, ...(d.projects ?? [])].some((x) => x?.toLowerCase().includes(s));
	const groups = $derived.by(() => {
		const s = q.trim().toLowerCase();
		const by = new Map<string, DatasetRow[]>();
		for (const d of loaded) {
			if (s && !match(d, s)) continue;
			const k = publisher(d);
			by.set(k, [...(by.get(k) ?? []), d]);
		}
		return [...by.entries()]
			.sort(([a], [b]) => a.localeCompare(b))
			.map(([agency, ds]) => ({ agency, ds: ds.sort((a, b) => a.title.localeCompare(b.title)) }));
	});
	const shown = $derived(groups.reduce((n, g) => n + g.ds.length, 0));
	const vintage = (d: DatasetRow) => d.vintage?.label ?? (d.vintage?.year ? String(d.vintage.year) : '');
</script>

<svelte:head><title>Methods & sources · Admin</title></svelte:head>

<h1>Methods & sources</h1>
<p class="lead">
	How the derived layers and analyses are calculated, and where every loaded dataset comes from with the credit its
	publisher asks for. Methods are files in <code>docs/methods/</code>; sources come from the import recipes in
	<code>data/recipes/</code>.
</p>

<div class="columns">
<section class="col-methods" aria-labelledby="methods-h">
<h2 id="methods-h">Methods</h2>
{#if data.methods.length}
	<ul class="list">
		{#each data.methods as m (m.id)}
			<li>
				<a href="/admin/methods/{m.id}">{m.title}</a>
				{#if m.project}<span class="sub">{m.project}{m.layer ? ` · ${m.layer}` : ''}</span>{/if}
				{#if m.process}<span class="sub">analysis · <code>{m.process}</code></span>{/if}
				<p>{m.summary}</p>
			</li>
		{/each}
	</ul>
{:else}
	<p class="sub">No methods yet. Add a JSON file to <code>docs/methods/</code>.</p>
{/if}
</section>

<section class="col-sources" aria-labelledby="sources-h">
	<div class="sources-head">
		<h2 id="sources-h">Sources</h2>
		<span class="sub">
			{loaded.length} loaded datasets from {new Set(loaded.map(publisher)).size} publishers{notLoaded
				? ` · ${notLoaded} recipes not loaded`
				: ''}
		</span>
		<label class="visually-hidden" for="src-q">Filter sources</label>
		<input id="src-q" type="search" placeholder="Filter by publisher, dataset, license or map…" bind:value={q} />
	</div>
	{#if q && shown === 0}
		<p class="sub">No source matches “{q}”.</p>
	{/if}
	{#each groups as g (g.agency)}
		<h3>{g.agency} <span class="count">{g.ds.length}</span></h3>
		<div class="table-wrap">
			<table>
				<thead>
					<tr><th scope="col">Dataset</th><th scope="col">Attribution</th><th scope="col">License</th><th scope="col">Vintage</th><th scope="col">Used on</th></tr>
				</thead>
				<tbody>
					{#each g.ds as d (d.name)}
						<tr>
							<td><a href="/admin/datasets/{d.name}">{d.title}</a></td>
							<td>{d.attribution ?? '—'}</td>
							<td>{d.license ?? '—'}</td>
							<td class="nowrap">{vintage(d) || '—'}</td>
							<td>{d.projects?.length ? d.projects.join(', ') : 'not on a map'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/each}
</section>
</div>

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.5rem; }
	h2 { font-size: 1.1rem; margin: 1.4rem 0 0.6rem; }
	h3 { font-size: 0.95rem; margin: 1.1rem 0 0.4rem; display: flex; align-items: center; gap: 0.4rem; }
	.lead { color: var(--muted); margin: 0 0 1rem; max-width: 75ch; }
	.list { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.8rem; }
	.list li { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.8rem 1rem; }
	.list a { font-weight: 600; }
	.list p { margin: 0.3rem 0 0; font-size: 0.9rem; max-width: 80ch; }
	.sub { font-size: 0.75rem; color: var(--muted); margin-left: 0.5rem; }
	code { font-size: 0.8rem; }
	/* Two columns: methods on the left, sources on the right. */
	.columns { display: grid; grid-template-columns: minmax(280px, 0.8fr) minmax(0, 1.4fr); gap: 1.5rem; align-items: start; }
	.col-methods { position: sticky; top: 1rem; }
	.col-methods h2, .sources-head h2 { margin-top: 0; }
	@media (max-width: 1000px) { .columns { grid-template-columns: 1fr; } .col-methods { position: static; } }
	.sources-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.4rem 0.8rem; margin-top: 0; }
	.sources-head h2 { margin: 0; }
	.sources-head .sub { margin-left: 0; }
	.sources-head input { margin-left: auto; min-width: min(100%, 260px); font: inherit; font-size: 0.85rem; padding: 0.35rem 0.55rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); }
	.count { font-size: 0.72rem; font-weight: 600; color: var(--muted); background: var(--surface-muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 0.45rem; }
	.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
	th, td { text-align: left; padding: 0.45rem 0.65rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	tbody tr:last-child td { border-bottom: none; }
	th { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); background: var(--surface-muted); }
	td:first-child { width: 28%; }
	.nowrap { white-space: nowrap; }
</style>
