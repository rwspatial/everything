<script lang="ts">
	// Printable community vulnerability assessment (Community Resilience Partnership, Track 2; SPG2026-7 section 2.5 C),
	// in the program's order. The data sections come from py.town_vulnerability; the community-informed sections (goals,
	// engagement, consequences, final priorities) are boxes for the service provider to complete with the town. The
	// reporter prints this page to PDF (POST /api/admin/projects/<slug>/reports {"page": "assessment"}).
	import { onMount } from 'svelte';
	import MapSnapshot from '$lib/components/MapSnapshot.svelte';
	import Legend from '$lib/components/Legend.svelte';
	import ExposureTable from '$lib/components/assessment/ExposureTable.svelte';
	import { PALETTE } from '$lib/format';
	import { title as pageTitle } from '$lib/site';
	import { HORIZONS, NRI_HAZARDS, TIER_COLORS, pct, rank } from '$lib/assessment';

	let { data } = $props();
	const m = $derived(data.manifest);
	const a = $derived(data.assessment);
	const config = $derived(data.config);
	const visible = $derived(m.layers.filter((l) => l.status !== 'todo' && l.visible !== false));
	const sources = $derived([...new Set(m.layers.filter((l) => l.status !== 'todo').map((l) => l.attribution).filter(Boolean))] as string[]);
	const scen = $derived(a.scenarios.filter((s) => s.present));
	const byId = $derived(Object.fromEntries(a.scenarios.map((s) => [s.id, s])));
	const n0 = new Intl.NumberFormat('en-US');
	const n1 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
	const date = (s: string | null) => (s ? new Date(s).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }) : '');
	const generated = date(new Date().toISOString());
	const t = $derived(a.people.town);
	const exposed = (asset: string, sc: string) => a.exposure.find((e) => e.asset === asset)?.by[sc]?.direct ?? 0;

	let mapReady = $state(false);
	let mapError = $state('');
	onMount(() => (window.__report = { ready: false }));
	$effect(() => {
		if (mapReady && window.__report) requestAnimationFrame(() => requestAnimationFrame(() => (window.__report = { ready: true })));
	});
</script>

<svelte:head><title>{pageTitle(`${a.town.short_name}: vulnerability assessment`)}</title></svelte:head>

<article class="doc">
	<header>
		<p class="brand">Downeast Geospatial · Community vulnerability assessment · draft for community review</p>
		<h1>{a.town.name}: vulnerability assessment</h1>
		<p class="meta">
			{a.town.county} County, Maine{a.town.pop ? ` · ${n0.format(a.town.pop)} residents` : ''}{a.town.area_sqmi ? ` · ${a.town.area_sqmi} sq mi` : ''}
			· data analysis {date(data.finished)} (run {data.jobId}) · printed {generated}
		</p>
	</header>

	<section aria-labelledby="s-about">
		<h2 id="s-about">About this assessment</h2>
		<p>
			A vulnerability assessment identifies priority climate risks and vulnerable assets and produces a prioritized,
			actionable set of recommendations to guide resilience planning and investment (Community Resilience Partnership).
			The data sections below were computed from public state and federal data for {a.town.short_name}: where flooding and
			sea level rise reach today and under the state's 2050 and 2100 planning targets, which buildings, homes, roads,
			critical facilities and structures lie there, how they rank, and who is most vulnerable. The shaded sections are
			completed with the community: its goals, what residents and staff know, the consequences of losing each asset,
			and the final priorities.
		</p>
		<div class="kpis">
			<div><b>{n0.format(exposed('Buildings', 'fema_1pct'))}</b><span>buildings in the 1% flood area</span></div>
			{#if a.town.coastal}
				<div><b>{n0.format(exposed('Buildings', 'slr_1_6'))}</b><span>at the 2050 sea level (+1.6 ft)</span></div>
				<div><b>{n0.format(exposed('Buildings', 'slr_3_9'))}</b><span>at the 2100 sea level (+3.9 ft)</span></div>
			{:else}
				<div><b>{n0.format(exposed('Buildings', 'fema_02pct'))}</b><span>in the 0.2% flood area</span></div>
			{/if}
			<div><b>{a.assets.filter((x) => x.tier === 'High').length}</b><span>high-risk key assets</span></div>
		</div>
	</section>

	<section aria-labelledby="s-goals" class="fill">
		<h2 id="s-goals">1. Community goals</h2>
		<p class="prompt">To complete with the town: what the community wants from this assessment (e.g. protect the working waterfront,
			keep the village center accessible, prepare an application for the next Community Action Grant), and whether to
			look at shared risks with neighbouring towns.</p>
		<div class="blank" style:height="1.1in"></div>
	</section>

	<section aria-labelledby="s-hazards">
		<h2 id="s-hazards">2. Hazards, impacts and planning horizons</h2>
		<div class="map">
			<MapSnapshot manifest={m} height={460} tilesBase={config.tilesBase} onready={(e) => { mapError = e ?? ''; mapReady = true; }} />
			{#if mapError}<p class="note">The map could not be drawn: {mapError}</p>{/if}
		</div>
		{#if visible.length}
			<div class="legend-grid">
				{#each visible as l, i (l.id)}
					<div class="legend-item"><div class="ltitle">{l.title}</div><Legend spec={l} color={PALETTE[i % PALETTE.length]} /></div>
				{/each}
			</div>
		{/if}
		<h3>Scenarios assessed</h3>
		<table>
			<thead><tr><th>Scenario</th><th>Source</th><th>Horizon</th><th>What it represents</th></tr></thead>
			<tbody>
				{#each a.scenarios as s (s.id)}
					<tr class:absent={!s.present}>
						<td><strong>{s.label}</strong></td><td>{s.source}</td><td>{s.horizon}</td>
						<td>{s.note}{#if !s.present} <em>Not present in {a.town.short_name}.</em>{/if}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="note">Sea level scenarios are the Maine Geological Survey's inundation areas at the Highest Astronomical Tide plus the
			stated rise, matched to the Maine Climate Council's targets (commit to manage 1.5 ft by 2050 and 3.9 ft by 2100; prepare
			to manage 3 ft by 2050 and 8.8 ft by 2100). A storm surge on top of a high tide reaches the same elevations sooner.</p>
		{#if Object.keys(a.people.nri_hazard_scores).length}
			<h3>Other natural hazards (FEMA National Risk Index)</h3>
			<p>Risk scores of the town's census tracts (national percentile, 0–100; higher means higher risk than more of the country):</p>
			<ul class="scores">
				{#each Object.entries(a.people.nri_hazard_scores).sort((x, y) => y[1] - x[1]) as [k, v] (k)}
					<li><span>{NRI_HAZARDS[k] ?? k}</span><span class="bar"><i style:width="{v}%"></i></span><b>{n1.format(v)}</b></li>
				{/each}
			</ul>
			<p class="note">Extreme heat, drought, wildfire and public health impacts are not mapped here; add them with the community where relevant.</p>
		{/if}
	</section>

	<section aria-labelledby="s-assets">
		<h2 id="s-assets">3. Vulnerability of valued community assets</h2>
		<p>How many of the town's assets each scenario reaches. Infrastructure and public property (roads, bridges, culverts, dams,
			wastewater), neighbourhoods (buildings and homes), community services (emergency, health, shelter, schools) and
			economic and recreational resources (boat launches), plus contaminated sites that could spread pollution when flooded.</p>
		<ExposureTable {a} />
		{#if Object.keys(a.roads_by_class).length}
			<h3>Road miles by class</h3>
			<table>
				<thead><tr><th>Class</th>{#each scen as s (s.id)}<th class="num">{s.label}</th>{/each}</tr></thead>
				<tbody>
					{#each [...new Set(Object.values(a.roads_by_class).flatMap((r) => Object.keys(r)))] as c (c)}
						<tr><th scope="row">{c}</th>{#each scen as s (s.id)}<td class="num">{a.roads_by_class[s.id]?.[c] ? n1.format(a.roads_by_class[s.id][c]) : '–'}</td>{/each}</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>

	<section aria-labelledby="s-risk">
		<h2 id="s-risk">4. Relative risk of priority assets</h2>
		<p>Each key asset the scenarios reach, ranked by how soon or how likely it is reached (1% flood or 2050 sea level first),
			how critical it is (emergency services, hospitals, shelters and nursing homes most), and its condition where rated.</p>
		{#if a.assets.length}
			<table>
				<thead><tr><th>Risk</th><th>Asset</th><th>Type</th><th>First reached</th><th>Condition</th><th>Consequence if impaired or lost <span class="hint">(with the town)</span></th></tr></thead>
				<tbody>
					{#each a.assets as x, i (i)}
						<tr>
							<td class="nowrap"><i class="dot" style:background={TIER_COLORS[x.tier]}></i>{x.tier}</td>
							<td><strong>{x.name}</strong>{#if x.detail}<br /><span class="hint">{x.detail}</span>{/if}</td>
							<td>{x.kind}</td>
							<td>{byId[x.first]?.label}<br /><span class="hint">{byId[x.first]?.horizon}{x.connection === 'barrier' ? ', behind a barrier' : ''}</span></td>
							<td>{x.condition ?? '–'}</td>
							<td class="blank-cell"></td>
						</tr>
					{/each}
				</tbody>
			</table>
		{:else}
			<p>None of the {a.assets_total} key assets mapped in {a.town.short_name} lie in these scenarios.</p>
		{/if}
	</section>

	<section aria-labelledby="s-people">
		<h2 id="s-people">5. At-risk populations</h2>
		<dl class="facts">
			{#if t.pop}<dt>Residents</dt><dd>{n0.format(t.pop)}{t.median_age ? `, median age ${t.median_age}` : ''}</dd>{/if}
			<dt>Aged 65 and over</dt><dd>{pct(t.pct_65_plus)}</dd>
			<dt>Below the poverty line</dt><dd>{pct(t.poverty_pct)}</dd>
			<dt>Seasonal homes</dt><dd>{pct(t.pct_seasonal)}</dd>
		</dl>
		{#if a.people.tracts.length}
			<table>
				<thead><tr><th>Census tract</th><th class="num">Share of town</th><th class="num">SVI overall</th><th class="num">Socio-economic</th><th class="num">Household</th><th class="num">Housing & transport</th><th class="num">No vehicle</th><th>NRI social vulnerability</th><th>NRI resilience</th></tr></thead>
				<tbody>
					{#each a.people.tracts as tr (tr.geoid)}
						<tr><td>{tr.name.split(';')[0]}</td><td class="num">{pct(tr.share)}</td><td class="num">{rank(tr.svi)}</td><td class="num">{rank(tr.svi_socioeconomic)}</td>
							<td class="num">{rank(tr.svi_household)}</td><td class="num">{rank(tr.svi_housing_transport)}</td><td class="num">{pct(tr.pct_no_vehicle)}</td>
							<td>{tr.nri_social_vulnerability ?? '–'}</td><td>{tr.nri_community_resilience ?? '–'}</td></tr>
					{/each}
				</tbody>
			</table>
			<p class="note">CDC/ATSDR Social Vulnerability Index 2022: national percentile rank, 0 (least) to 1 (most vulnerable); 0.75 and above is the top quarter.</p>
		{/if}
		<div class="fill">
			<p class="prompt">With the community: who in town is most affected (older residents living alone, people without a car, seasonal
				workers, residents of mobile homes or flood-prone neighbourhoods), how they were reached and what they said.</p>
			<div class="blank" style:height="1in"></div>
		</div>
	</section>

	<section aria-labelledby="s-actions">
		<h2 id="s-actions">6. Recommendations</h2>
		<p>Draft candidate actions drawn from the numbers above, for the community to review, add to and rank. Funding sources are
			examples to check against current programs.</p>
		{#each HORIZONS as h (h)}
			{@const xs = a.actions.filter((x) => x.horizon === h)}
			{#if xs.length}
				<h3>{h} actions</h3>
				<table>
					<thead><tr><th>Action</th><th>Why (from this assessment)</th><th>Possible funding</th><th>Priority <span class="hint">(town)</span></th></tr></thead>
					<tbody>{#each xs as x, i (i)}<tr><td>{x.action}</td><td>{x.evidence}</td><td>{x.funding}</td><td class="blank-cell"></td></tr>{/each}</tbody>
				</table>
			{/if}
		{/each}
		<div class="fill">
			<p class="prompt">Regional or joint recommendations with neighbouring towns, resource needs and next steps (who leads, what it costs,
				which application comes next).</p>
			<div class="blank" style:height="1.1in"></div>
		</div>
	</section>

	<section aria-labelledby="s-methods" class="methods">
		<h2 id="s-methods">Methods and sources</h2>
		<p>Assets are counted where any part of them touches a scenario; road figures are the miles inside it. Relative risk multiplies
			how soon or how likely an asset is reached (3: 1% flood or 2050 sea level; 2: 0.2% flood or 3.9 ft; 1: 8.8 ft; one less behind a
			barrier) by its criticality (3: emergency services, hospitals, shelters, nursing homes; 2: schools, bridges, culverts, dams,
			contaminated sites and wastewater; 1: other), plus 2 for poor or critical condition: High from 7, Medium from 4. Full method:
			the platform's methods page, town vulnerability assessment (version {a.method.version}).</p>
		<ul>{#each sources as s (s)}<li>{s}</li>{/each}<li>CDC/ATSDR Social Vulnerability Index 2022; FEMA National Risk Index; E911 address points and roads (Maine GeoLibrary); Maine DEP remediation, landfill and licensed discharge sites</li></ul>
		<p class="note">Public data, screening level: FEMA flood maps and building footprints can be out of date or misplaced, and sea level
			scenarios do not model waves, erosion or drainage. Field-check priority assets before investing. Basemap © OpenFreeMap,
			OpenMapTiles, OpenStreetMap contributors.</p>
	</section>
</article>

<style>
	:global(html:root), :global(body) { background: #fff; }
	.doc { max-width: 7.4in; margin: 0 auto; padding: 0.3in 0 0.5in; color: #1d2733; font-size: 10pt; line-height: 1.4; }
	header { border-bottom: 2px solid #1d2733; padding-bottom: 0.1in; margin-bottom: 0.12in; }
	.brand { margin: 0; font-size: 8pt; letter-spacing: 0.06em; text-transform: uppercase; color: #5b6670; }
	h1 { margin: 0.04in 0; font-size: 20pt; line-height: 1.15; }
	h2 { font-size: 12.5pt; margin: 0.24in 0 0.08in; border-bottom: 1px solid #d5dbe1; padding-bottom: 0.04in; break-after: avoid; }
	h3 { font-size: 10.5pt; margin: 0.14in 0 0.05in; break-after: avoid; }
	p { margin: 0.05in 0; }
	.meta, .note, .hint { font-size: 8.5pt; color: #5b6670; }
	.meta { margin: 0; }
	.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.1in; margin: 0.1in 0; }
	.kpis div { border: 1px solid #d5dbe1; border-radius: 6px; padding: 0.06in 0.08in; display: grid; }
	.kpis b { font-size: 16pt; }
	.kpis span { font-size: 8pt; color: #5b6670; }
	.fill { background: #f4f6f8; border: 1px dashed #b8c2cc; border-radius: 6px; padding: 0.06in 0.1in; margin: 0.08in 0; break-inside: avoid; }
	section.fill { padding-top: 0.01in; }
	.prompt { font-style: italic; color: #3b4753; }
	.blank { border-bottom: 1px solid #d5dbe1; }
	table { width: 100%; border-collapse: collapse; font-size: 8.5pt; margin: 0.05in 0; break-inside: auto; }
	th, td { text-align: left; padding: 0.03in 0.05in; border-bottom: 1px solid #e3e8ed; vertical-align: top; }
	thead th { font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.03em; color: #5b6670; background: #f4f6f8; }
	tr { break-inside: avoid; }
	.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
	.nowrap { white-space: nowrap; }
	.absent td { color: #8a949e; }
	.blank-cell { min-width: 1.2in; background: #f4f6f8; }
	.dot { display: inline-block; width: 0.6em; height: 0.6em; border-radius: 2px; margin-right: 0.3em; border: 1px solid rgb(0 0 0 / 0.15); }
	.map { break-inside: avoid; }
	.legend-grid { columns: 3; column-gap: 0.18in; margin-top: 0.06in; }
	.legend-item { break-inside: avoid; margin-bottom: 0.04in; }
	.ltitle { font-weight: 600; font-size: 7.5pt; }
	.legend-grid :global(.legend) { font-size: 7pt; line-height: 1.25; margin: 0; }
	.legend-grid :global(.legend .swatch) { width: 9px; height: 9px; }
	.scores { list-style: none; margin: 0.04in 0; padding: 0; display: grid; gap: 0.03in; max-width: 5in; }
	.scores li { display: grid; grid-template-columns: 1.8in 1fr 0.45in; align-items: center; gap: 0.08in; font-size: 9pt; }
	.scores .bar { height: 7px; background: #e9edf1; border-radius: 4px; overflow: hidden; }
	.scores .bar i { display: block; height: 100%; background: #d6604d; }
	.scores b { text-align: right; font-variant-numeric: tabular-nums; }
	.facts { display: grid; grid-template-columns: auto 1fr; gap: 0.02in 0.15in; margin: 0.05in 0; font-size: 9.5pt; }
	.facts dt { color: #5b6670; }
	.facts dd { margin: 0; }
	.methods ul { margin: 0.04in 0; padding-left: 1.1em; font-size: 8.5pt; }
	.doc :global(.table-wrap) { overflow: visible; border: none; }
	.doc :global(table.exposure) { font-size: 8pt; }
	@media print {
		.doc { padding: 0; max-width: none; }
	}
</style>
