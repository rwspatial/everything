<script lang="ts">
	// The tiles & features API (tiPG, OGC API Features + Tiles) seen from the admin: what it is, its documentation, and
	// every collection grouped by the project that publishes it, with the URLs the maps and other clients use.
	let { data } = $props();
	let q = $state('');
	const groups = $derived.by(() => {
		const s = q.trim().toLowerCase();
		const by = new Map<string, string[]>();
		for (const c of data.collections) {
			if (s && !c.id.toLowerCase().includes(s)) continue;
			const name = c.id.replace(/^pub\./, '');
			const project = name.includes('__') ? name.split('__')[0].replaceAll('_', '-') : 'other';
			by.set(project, [...(by.get(project) ?? []), c.id]);
		}
		// Map projects first; analysis results (one collection per run) last.
		const last = (p: string) => (p === 'analysis-sandbox' ? 1 : 0);
		return [...by.entries()].sort(([a], [b]) => last(a) - last(b) || a.localeCompare(b));
	});
	const shown = $derived(groups.reduce((n, [, ids]) => n + ids.length, 0));
	const DOCS = [
		{ href: '/', label: 'Landing page', hint: 'the API root and its links' },
		{ href: '/collections', label: 'Collection catalogue', hint: 'every published view and function' },
		{ href: '/api.html', label: 'API reference', hint: 'OpenAPI documentation (try requests)' },
		{ href: '/tileMatrixSets', label: 'Tile matrix sets', hint: 'the tiling schemes, e.g. WebMercatorQuad' },
		{ href: '/conformance', label: 'Conformance', hint: 'the OGC standards it implements' }
	];
</script>

<svelte:head><title>Tiles & features API · Admin</title></svelte:head>

<h1>Tiles &amp; features API</h1>
<p class="lead">
	Every map layer is read from this API: tiPG serves the published views and functions in PostGIS (the <code>pub</code>
	schema) as vector tiles and GeoJSON features, following the OGC API Features and Tiles standards. On the public site only
	the map tiles and feature items of a collection are served; the catalogue, collection pages and documentation below are
	admin-only.
</p>

<ul class="docs">
	{#each DOCS as d (d.href)}
		<li><a href="{data.base}{d.href}" rel="external" target="_blank">{d.label}</a><span>{d.hint}</span></li>
	{/each}
</ul>

<div class="head">
	<h2>Collections <span class="count">{data.collections.length}</span></h2>
	<label class="visually-hidden" for="api-q">Filter collections</label>
	<input id="api-q" type="search" placeholder="Filter by name…" bind:value={q} />
</div>
{#if data.error}<p class="error" role="alert">The API did not answer: {data.error}</p>{/if}
{#if q && !shown}<p class="sub">No collection matches “{q}”.</p>{/if}
{#each groups as [project, ids] (project)}
	<h3>{project} <span class="count">{ids.length}</span></h3>
	<div class="table-wrap">
		<table>
			<thead><tr><th scope="col">Collection</th><th scope="col">Vector tiles</th><th scope="col">Features</th></tr></thead>
			<tbody>
				{#each ids as id (id)}
					<tr>
						<td><a href="{data.base}/collections/{id}" rel="external" target="_blank">{id}</a></td>
						<td><code>{data.base}/collections/{id}/tiles/WebMercatorQuad/&#123;z&#125;/&#123;x&#125;/&#123;y&#125;</code></td>
						<td><a href="{data.base}/collections/{id}/items?f=geojson&amp;limit=10" rel="external" target="_blank">GeoJSON sample</a></td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/each}

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.5rem; }
	h2 { font-size: 1.1rem; margin: 0; display: flex; align-items: center; gap: 0.4rem; }
	h3 { font-size: 0.92rem; margin: 1rem 0 0.35rem; display: flex; align-items: center; gap: 0.4rem; }
	.lead { color: var(--muted); margin: 0 0 1rem; max-width: 85ch; }
	.docs { list-style: none; padding: 0; margin: 0 0 1.4rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.5rem; }
	.docs li { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 0.5rem 0.7rem; display: grid; gap: 0.1rem; }
	.docs a { font-weight: 600; }
	.docs span { font-size: 0.76rem; color: var(--muted); }
	.head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem 1rem; }
	.head input { margin-left: auto; min-width: min(100%, 260px); font: inherit; font-size: 0.85rem; padding: 0.35rem 0.55rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); }
	.count { font-size: 0.72rem; font-weight: 600; color: var(--muted); background: var(--surface-muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 0.45rem; }
	.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
	th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	tbody tr:last-child td { border-bottom: none; }
	th { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); background: var(--surface-muted); }
	td code { font-size: 0.74rem; color: var(--muted); word-break: break-all; }
	.sub { font-size: 0.8rem; color: var(--muted); }
	.error { color: #b42318; }
</style>
