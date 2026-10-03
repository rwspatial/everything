<script lang="ts">
	// Printable report of one project (plan: project-builder §1.6): title block, the map as a still picture, legends,
	// every chart (the same D3 charts as the viewer, computed on the fly) and sources. The reporter service prints
	// this page to PDF; it sets window.__report.ready once the map and all charts are in.
	import { onMount } from 'svelte';
	import MapSnapshot from '$lib/components/MapSnapshot.svelte';
	import Legend from '$lib/components/Legend.svelte';
	import Chart, { type ChartData } from '$lib/charts/Chart.svelte';
	import { PALETTE } from '$lib/format';
	import { title as pageTitle } from '$lib/site';
	import type { ChartSpec } from '$lib/contracts.gen';

	let { data } = $props();
	const manifest = $derived(data.manifest);
	const config = $derived(data.config);

	const visible = $derived(manifest.layers.filter((l) => l.status !== 'todo' && l.visible !== false));
	const sources = $derived([...new Set(manifest.layers.filter((l) => l.status !== 'todo').map((l) => l.attribution).filter(Boolean))] as string[]);
	const charts = $derived((manifest.charts ?? []) as ChartSpec[]);

	// Page one holds the title block, the map and the legend together (a Letter page has 9.85 in inside the
	// reporter's margins). The map takes what the header and the legend leave: about 4 to 6.4 in.
	// Legend height in lines: entries never split across the four columns, so the tallest entry is a floor.
	const entryLines = $derived(
		visible.map((l) => 1 + (l.legend?.type === 'categorical' ? l.legend.items.length + (l.legend.title ? 1 : 0) : l.legend?.type === 'none' ? 0 : 1))
	);
	const legendLines = $derived(Math.max(...entryLines, 0, Math.ceil(entryLines.reduce((a, b) => a + b, 0) / 4)) * 4);
	const mapHeight = $derived.by(() => {
		const header = 1.05 + Math.ceil((manifest.description?.length ?? 0) / 105) * 0.19;
		const legend = visible.length ? 0.45 + (legendLines / 4) * 0.16 : 0;
		const inches = Math.min(6.4, Math.max(4, 9.75 - header - legend - 0.15));
		return Math.round(inches * 96);
	});
	const generated = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

	let chartData: Record<string, ChartData | { error: string }> = $state({});
	let mapReady = $state(false);
	let mapError = $state('');

	onMount(() => {
		window.__report = { ready: false };
		const b = manifest.view.bounds;
		Promise.all(
			charts.map(async (c) => {
				// "In view" charts use the map's framing in the report.
				const q = c.scope === 'view' && b ? `?bbox=${b.map((v) => v.toFixed(4)).join(',')}` : '';
				try {
					const r = await fetch(`/api/projects/${manifest.slug}/charts/${c.id}${q}`);
					const body = await r.json();
					chartData[c.id] = r.ok ? body : { error: typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}` };
				} catch (e) {
					chartData[c.id] = { error: (e as Error).message };
				}
			})
		).then(() => {
			chartsDone = true;
		});
	});
	let chartsDone = $state(false);
	$effect(() => {
		if (mapReady && chartsDone && window.__report) {
			// Two frames for the last charts to paint before printing.
			requestAnimationFrame(() => requestAnimationFrame(() => (window.__report = { ready: true })));
		}
	});
</script>

<svelte:head><title>{pageTitle(`${manifest.title}: report`)}</title></svelte:head>

<article class="report">
	<div class="page-one" class:break={charts.length > 0}>
	<header>
		<p class="brand">Downeast Geospatial · Map report</p>
		<h1>{manifest.title}</h1>
		<p class="meta">Generated {generated} · live map at <a href="/p/{manifest.slug}">/p/{manifest.slug}</a></p>
		{#if manifest.description}<p class="lead">{manifest.description}</p>{/if}
	</header>

	<section class="map" aria-label="Map">
		<MapSnapshot
			{manifest}
			height={mapHeight}
			tilesBase={config.tilesBase}
			onready={(e) => {
				mapError = e ?? '';
				mapReady = true;
			}}
		/>
		{#if mapError}<p class="note">The map could not be drawn: {mapError}</p>{/if}
	</section>

	{#if visible.length}
		<section class="legends" aria-label="Legend">
			<h2>Legend</h2>
			<div class="legend-grid">
				{#each visible as l, i (l.id)}
					<div class="legend-item">
						<div class="ltitle">{l.title}</div>
						<Legend spec={l} color={PALETTE[i % PALETTE.length]} />
					</div>
				{/each}
			</div>
		</section>
	{/if}
	</div>

	{#if charts.length}
		<section class="charts" aria-label="Charts">
			<h2>Charts</h2>
			<div class="chart-grid">
				{#each charts as c (c.id)}
					{@const d = chartData[c.id]}
					<div class="chart-cell" class:wide={c.type === 'stats' || c.type === 'scatter'}>
						{#if !d}
							<p class="note">Loading {c.title}…</p>
						{:else if 'error' in d}
							<p class="note">{c.title}: {d.error}</p>
						{:else}
							<Chart spec={c} data={d} />
							{#if c.scope === 'view'}<p class="note">Within the map frame above.</p>{/if}
						{/if}
					</div>
				{/each}
			</div>
		</section>
	{/if}

	<section class="sources" aria-label="Sources">
		<h2>Sources</h2>
		<ul>{#each sources as s (s)}<li>{s}</li>{/each}</ul>
		<p class="note">Basemap © OpenFreeMap, OpenMapTiles, OpenStreetMap contributors. Figures are computed from the published data at the time of printing.</p>
	</section>
</article>

<style>
	/* White to the edge of every page: the site's grey page background would print below the last line. */
	:global(html:root), :global(body) { background: #fff; } /* html:root outranks app.css's :root */
	.report { max-width: 7.4in; margin: 0 auto; padding: 0.3in 0 0.5in; color: #1d2733; font-size: 10.5pt; }
	header { border-bottom: 2px solid #1d2733; padding-bottom: 0.1in; margin-bottom: 0.14in; }
	.brand { margin: 0; font-size: 8.5pt; letter-spacing: 0.06em; text-transform: uppercase; color: #5b6670; }
	h1 { margin: 0.04in 0; font-size: 20pt; line-height: 1.15; }
	h2 { font-size: 12pt; margin: 0.22in 0 0.08in; border-bottom: 1px solid #d5dbe1; padding-bottom: 0.04in; }
	.meta { margin: 0; font-size: 8.5pt; color: #5b6670; }
	.meta a { color: inherit; }
	.lead { margin: 0.08in 0 0; color: #3b4753; }
	.page-one.break { break-after: page; }
	.legends h2 { margin-top: 0.12in; }
	.legend-grid { columns: 4; column-gap: 0.18in; }
	.legend-item { break-inside: avoid; margin-bottom: 0.05in; }
	.ltitle { font-weight: 600; font-size: 7.5pt; line-height: 1.25; }
	.legends :global(.legend) { margin: 0.02in 0 0; font-size: 7pt; line-height: 1.25; }
	.legends :global(.legend .title) { font-size: 7pt; margin-bottom: 0.02in; }
	.legends :global(.legend ul) { gap: 0.01in; }
	.legends :global(.legend .swatch) { width: 9px; height: 9px; }
	.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.18in 0.28in; }
	.chart-cell { break-inside: avoid; min-width: 0; }
	.chart-cell.wide { grid-column: 1 / -1; }
	.sources ul { margin: 0; padding-left: 1.1em; font-size: 9pt; }
	.note { font-size: 8.5pt; color: #5b6670; margin: 0.04in 0 0; }
	.map { break-inside: avoid; }
	/* The report shows charts, not their table toggles. */
	.report :global(.table-toggle) { display: none; }
	@media print {
		.report { padding: 0; max-width: none; }
		a { text-decoration: none; }
	}
</style>
