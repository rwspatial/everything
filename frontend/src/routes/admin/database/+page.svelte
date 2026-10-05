<script lang="ts">
	import { onMount } from 'svelte';
	import Badge from '$lib/admin/Badge.svelte';
	import SortTh from '$lib/admin/SortTh.svelte';
	import { TableSort } from '$lib/admin/sort.svelte';
	import { api, fmtAgo, fmtBytes, fmtDate, fmtNum, type DatabaseHealth, type DbTable, type DbView } from '$lib/admin/api';

	let data = $state<DatabaseHealth | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let allViews = $state(false);
	let issuesOnly = $state(false);

	async function load(refresh = false) {
		busy = true;
		try {
			data = await api<DatabaseHealth>(fetch, `/database${refresh ? '?refresh=true' : ''}`);
			error = null;
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}
	onMount(() => void load());

	const viewOk = (v: DbView) => v.spatial_index_usable === true;
	const viewSort = new TableSort<DbView>(
		{ view: (v) => v.name, type: (v) => v.geometry_type, sources: (v) => v.sources.join(', '), status: (v) => (viewOk(v) ? 1 : 0) },
		{ key: 'status' }
	);
	const shownViews = $derived(data ? data.views.filter((v) => allViews || !viewOk(v)) : []);

	// Share of scans that were full scans: high on a big table usually means a view or query that cannot use an index.
	const seqShare = (t: DbTable) => {
		const s = t.seq_scan ?? 0;
		const i = t.idx_scan ?? 0;
		return s + i ? s / (s + i) : null;
	};
	const level = (t: DbTable) => (t.issues.some((i) => i.level === 'fail') ? 'fail' : t.issues.length ? 'warn' : 'ok');
	const tableSort = new TableSort<DbTable>(
		{
			table: (t) => `${t.schema}.${t.name}`,
			rows: (t) => t.rows,
			size: (t) => t.bytes,
			type: (t) => t.geometry_type,
			index: (t) => (t.geom ? (t.spatial_index ? 1 : 0) : null),
			analyzed: (t) => t.last_analyzed,
			seq: (t) => t.seq_scan,
			idx: (t) => t.idx_scan,
			share: (t) => seqShare(t),
			status: (t) => ({ fail: 0, warn: 1, ok: 2 })[level(t)]
		},
		{ key: 'size', dir: 'desc' }
	);
	const shownTables = $derived(data ? data.tables.filter((t) => !issuesOnly || t.issues.length) : []);
</script>

<svelte:head><title>Database tables &amp; views · Admin</title></svelte:head>

<div class="head">
	<div>
		<h1>Database tables &amp; views</h1>
		<p class="lead">
			Spatial indexes, geometry types and scan statistics. The key check: can each published view's tile filter use a
			spatial index? If not, every map tile scans the whole source table.
		</p>
	</div>
	<button type="button" onclick={() => load(true)} disabled={busy}>{busy ? 'Checking…' : 'Check now'}</button>
</div>

{#if error}<p class="err" role="alert">{error}</p>{/if}

{#if data}
	{@const s = data.summary}
	<section class="cards" aria-label="Summary">
		<div class="card {s.views_indexed === s.views ? 'good' : 'bad'}">
			<span class="big">{s.views_indexed} / {s.views}</span>
			<span>published views can use a spatial index</span>
		</div>
		<div class="card {s.tables_with_issues ? 'warn' : 'good'}">
			<span class="big">{s.tables_with_issues}</span>
			<span>of {s.tables} source tables with issues</span>
		</div>
		<div class="card">
			<span class="big">{fmtBytes(data.db_bytes)}</span>
			<span>database size</span>
		</div>
		<div class="card">
			<span class="big">{fmtBytes(s.unused_index_bytes)}</span>
			<span>in indexes never used</span>
		</div>
	</section>
	<p class="sub">
		Checked {fmtAgo(data.checked_at)} (results are cached for a minute). Scan counts are totals since
		{data.stats_since ? fmtDate(data.stats_since) : 'the database was created'}, so they include history from before
		any fix.
	</p>

	<h2>Published views</h2>
	<label class="toggle"><input type="checkbox" bind:checked={allViews} /> Show all {data.views.length} views (default: only problems)</label>
	{#if shownViews.length}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<SortTh sort={viewSort} key="view">View</SortTh><SortTh sort={viewSort} key="type">Geometry</SortTh>
						<SortTh sort={viewSort} key="sources">Reads from</SortTh><SortTh sort={viewSort} key="status">Spatial index</SortTh>
					</tr>
				</thead>
				<tbody>
					{#each viewSort.apply(shownViews) as v (v.name)}
						<tr>
							<td><code>pub.{v.name}</code>{#if v.analysis_output}<span class="sub"> analysis output</span>{/if}</td>
							<td>{v.geometry_type ?? '–'}</td>
							<td class="sub">{v.sources.join(', ') || '–'}</td>
							<td>
								{#if viewOk(v)}<Badge value="ok" />
								{:else if v.error}<Badge value="error" title={v.error} /> <span class="sub">{v.error}</span>
								{:else}<Badge value="fail" /> <span class="sub">geometry is wrapped in an expression; pass the column through</span>{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<p class="ok" role="status">Every published view can use a spatial index for its tile filter.</p>
	{/if}

	<h2>Source tables</h2>
	<label class="toggle"><input type="checkbox" bind:checked={issuesOnly} /> Only tables with issues</label>
	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<SortTh sort={tableSort} key="table">Table</SortTh><SortTh sort={tableSort} key="rows" class="num">Rows</SortTh>
					<SortTh sort={tableSort} key="size" class="num">Size</SortTh><SortTh sort={tableSort} key="type">Geometry</SortTh>
					<SortTh sort={tableSort} key="index">Spatial index</SortTh><SortTh sort={tableSort} key="analyzed">Analyzed</SortTh>
					<SortTh sort={tableSort} key="seq" class="num">Full scans</SortTh><SortTh sort={tableSort} key="idx" class="num">Index scans</SortTh>
					<SortTh sort={tableSort} key="share" class="num">Full-scan share</SortTh><SortTh sort={tableSort} key="status">Status</SortTh>
				</tr>
			</thead>
			<tbody>
				{#each tableSort.apply(shownTables) as t (t.schema + '.' + t.name)}
					{@const share = seqShare(t)}
					<tr>
						<td><code>{t.schema}.{t.name}</code></td>
						<td class="num">{fmtNum(t.rows)}</td>
						<td class="num">{fmtBytes(t.bytes)}</td>
						<td>{t.geom ? `${t.geometry_type}${(t.dims ?? 2) > 2 ? ` (${t.dims}D)` : ''}` : 'no geometry'}</td>
						<td>{t.geom ? (t.spatial_index ? 'GiST' : 'missing') : '–'}</td>
						<td title={fmtDate(t.last_analyzed)}>{fmtAgo(t.last_analyzed)}</td>
						<td class="num">{fmtNum(t.seq_scan)}</td>
						<td class="num">{fmtNum(t.idx_scan)}</td>
						<td class="num" class:hot={share !== null && share > 0.5 && t.rows > 50000}>
							{share === null ? '–' : `${Math.round(share * 100)}%`}
						</td>
						<td>
							<Badge value={level(t)} />
							{#each t.issues as i (i.code)}<div class="sub">{i.message}</div>{/each}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<p class="sub">
		Full-scan share is highlighted for tables over 50,000 rows scanned mostly in full. Some full scans are expected
		(statewide tiles at low zoom, health checks, imports); a high share that keeps growing points to a view or query
		that cannot use an index.
	</p>

	<h2>Unused indexes</h2>
	{#if data.unused_indexes.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Index</th><th>Table</th><th>Method</th><th class="num">Size</th></tr></thead>
				<tbody>
					{#each data.unused_indexes as u (u.index)}
						<tr><td><code>{u.index}</code></td><td><code>{u.table}</code></td><td>{u.method}</td><td class="num">{fmtBytes(u.bytes)}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="sub">Never scanned since statistics began (over 1 MB, excluding primary keys and unique constraints). Usually a layer nothing draws yet; not urgent.</p>
	{:else}
		<p class="sub">None over 1 MB.</p>
	{/if}
{:else if !error}
	<p class="sub">Checking…</p>
{/if}

<style>
	.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
	h1 { margin: 0 0 0.3rem; font-size: 1.5rem; }
	h2 { font-size: 1rem; margin: 1.4rem 0 0.5rem; }
	.lead { color: var(--muted); margin: 0; max-width: 75ch; }
	.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.8rem; margin: 1rem 0 0.4rem; }
	.card { background: var(--surface); border: 1px solid var(--border); border-left-width: 4px; border-radius: 10px; padding: 0.7rem 0.9rem; display: grid; gap: 0.15rem; font-size: 0.85rem; color: var(--muted); }
	.card.good { border-left-color: #2e7d32; }
	.card.warn { border-left-color: #b26a00; }
	.card.bad { border-left-color: #b42318; }
	.big { font-size: 1.4rem; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
	.toggle { display: inline-flex; gap: 0.4rem; align-items: center; font-size: 0.85rem; margin-bottom: 0.5rem; }
	.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
	table :global(th), td { text-align: left; padding: 0.5rem 0.65rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	table :global(th.num) { text-align: right; }
	table :global(th) { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); background: var(--surface-muted); }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.hot { color: #b42318; font-weight: 600; }
	.sub { font-size: 0.75rem; color: var(--muted); }
	.ok { color: #1b7837; }
	.err { background: #fde3e1; color: #8a1c14; padding: 0.5rem 0.8rem; border-radius: 8px; }
	button { font: inherit; font-size: 0.85rem; padding: 0.4rem 0.8rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; white-space: nowrap; }
	button:disabled { opacity: 0.6; cursor: progress; }
	code { font-size: 0.8rem; }
</style>
