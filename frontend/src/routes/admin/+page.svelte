<script lang="ts">
	import Badge from '$lib/admin/Badge.svelte';
	import SortTh from '$lib/admin/SortTh.svelte';
	import { TableSort } from '$lib/admin/sort.svelte';
	import { fmtAgo, fmtBytes, fmtNum, post } from '$lib/admin/api';

	let { data } = $props();

	let q = $state('');
	let kind = $state('');
	let group = $state('');
	let status = $state('');
	let staleOnly = $state(false);

	const kinds = $derived([...new Set(data.datasets.map((d) => d.kind))].sort());
	const groups = $derived([...new Set(data.datasets.map((d) => d.group_name ?? '(none)'))].sort());
	const statuses = $derived([...new Set(data.datasets.map((d) => d.status))].sort());

	const shown = $derived(
		data.datasets.filter((d) => {
			const text = `${d.name} ${d.title} ${d.agency ?? ''} ${d.description ?? ''}`.toLowerCase();
			return (
				(!q || text.includes(q.toLowerCase())) &&
				(!kind || d.kind === kind) &&
				(!group || (d.group_name ?? '(none)') === group) &&
				(!status || d.status === status) &&
				(!staleOnly || d.freshness === 'stale' || d.parts_current < d.parts_total)
			);
		})
	);
	type Row = (typeof data.datasets)[number];
	const sort = new TableSort<Row>({
		dataset: (d) => d.title,
		status: (d) => d.status,
		freshness: (d) => d.freshness,
		outputs: (d) => d.outputs_total,
		coverage: (d) => d.extent_name ?? d.coverage?.extent,
		features: (d) => d.rows,
		size: (d) => d.bytes,
		used: (d) => (d.projects ?? []).join(', '),
		last: (d) => d.last_run?.finished_at ?? d.last_run?.started_at
	});
	const summary = $derived({
		total: data.datasets.length,
		ok: data.datasets.filter((d) => d.status === 'ok').length,
		attention: data.datasets.filter((d) => ['failed', 'unhealthy', 'stale'].includes(d.status)).length
	});

	// Queue a freshness or health check for every enabled dataset (the dataset worker runs them).
	let bulkBusy = $state(false);
	let bulkMessage = $state('');
	async function checkAll(action: 'freshness' | 'healthcheck') {
		bulkBusy = true;
		try {
			const r = await post<{ queued: number; already_queued: number }>(fetch, '/datasets/actions', { action });
			bulkMessage =
				`${r.queued} ${action === 'freshness' ? 'update checks' : 'health checks'} queued` +
				(r.already_queued ? ` (${r.already_queued} already waiting)` : '') +
				'; see Jobs & runs.';
		} catch (e) {
			bulkMessage = (e as Error).message;
		} finally {
			bulkBusy = false;
		}
	}
</script>

<svelte:head><title>Datasets · Admin</title></svelte:head>

<header class="head">
	<h1>Datasets</h1>
	<p>
		Every dataset defined in <code>data/recipes/</code>: what we hold, how fresh it is, where it is published and how
		the last run went. <strong>{summary.total}</strong> datasets · <strong>{summary.ok}</strong> ok ·
		<strong>{summary.attention}</strong> need attention.
	</p>
	<p class="bulk">
		<button type="button" onclick={() => checkAll('freshness')} disabled={bulkBusy}>Check all for updates</button>
		<button type="button" onclick={() => checkAll('healthcheck')} disabled={bulkBusy}>Re-check all health</button>
		{#if bulkMessage}<span role="status">{bulkMessage}</span>{/if}
	</p>
</header>

<form class="filters" onsubmit={(e) => e.preventDefault()} aria-label="Filter datasets">
	<label>Search <input type="search" bind:value={q} placeholder="name, agency, text" /></label>
	<label>Kind
		<select bind:value={kind}><option value="">all</option>{#each kinds as k (k)}<option>{k}</option>{/each}</select>
	</label>
	<label>Group
		<select bind:value={group}><option value="">all</option>{#each groups as g (g)}<option>{g}</option>{/each}</select>
	</label>
	<label>Status
		<select bind:value={status}><option value="">all</option>{#each statuses as s (s)}<option>{s}</option>{/each}</select>
	</label>
	<label class="check"><input type="checkbox" bind:checked={staleOnly} /> Stale only</label>
</form>

<div class="table-wrap">
	<table class="datasets">
		<caption class="visually-hidden">Datasets ({shown.length} shown)</caption>
		<thead>
			<tr>
				<SortTh {sort} key="dataset">Dataset</SortTh>
				<SortTh {sort} key="status">Status</SortTh>
				<SortTh {sort} key="freshness">Freshness</SortTh>
				<SortTh {sort} key="outputs">Outputs</SortTh>
				<SortTh {sort} key="coverage">Coverage</SortTh>
				<SortTh {sort} key="features" class="num">Features</SortTh>
				<SortTh {sort} key="size" class="num">Size</SortTh>
				<SortTh {sort} key="used">Used by</SortTh>
				<SortTh {sort} key="last">Last run</SortTh>
			</tr>
		</thead>
		<tbody>
			{#each sort.apply(shown) as d (d.name)}
				<tr class:disabled={!d.enabled}>
					<td>
						<a class="name" href="/admin/datasets/{d.name}">{d.title}</a>
						<div class="sub"><code>{d.name}</code> · {d.kind}{d.group_name ? ` · ${d.group_name}` : ''}</div>
						{#if d.sync_error}<div class="err">sync error: {d.sync_error}</div>{/if}
						{#if d.orphaned}<div class="err">YAML file removed (orphaned)</div>{/if}
					</td>
					<td><Badge value={d.status} /></td>
					<td>
						<Badge value={d.freshness ?? 'unknown'} title={d.freshness_checked_at ? `checked ${fmtAgo(d.freshness_checked_at)}` : 'never checked'} />
						{#if d.parts_total > 1}<div class="sub">{d.parts_current}/{d.parts_total} parts current</div>{/if}
					</td>
					<td>
						{#if d.outputs_total}
							<span class="health" title="{d.health_ok} ok, {d.health_warn} warning, {d.health_fail} failing">
								<span class="dot ok"></span>{d.health_ok}
								{#if d.health_warn}<span class="dot warn"></span>{d.health_warn}{/if}
								{#if d.health_fail}<span class="dot fail"></span>{d.health_fail}{/if}
							</span>
						{:else}–{/if}
					</td>
					<td>{d.extent_name ?? d.coverage?.extent ?? '–'}{#if d.received_ratio !== null}<div class="sub">{Math.round(d.received_ratio * 100)} % received</div>{/if}</td>
					<td class="num">{fmtNum(d.rows)}</td>
					<td class="num">{fmtBytes(d.bytes)}</td>
					<td>{#each d.projects ?? [] as p (p)}<a class="proj" href="/p/{p}">{p}</a>{:else}–{/each}</td>
					<td>
						{#if d.last_run}
							<a href="/admin/runs/{d.last_run.id}"><Badge value={d.last_run.status} /></a>
							<div class="sub">{fmtAgo(d.last_run.finished_at ?? d.last_run.started_at)} · {d.last_run.triggered_by}</div>
						{:else}<span class="sub">never run</span>{/if}
					</td>
				</tr>
			{:else}
				<tr><td colspan="9" class="empty">No datasets match the filters.</td></tr>
			{/each}
		</tbody>
	</table>
</div>

{#if data.adhoc.length}
	<section class="adhoc">
		<h2>Ad hoc imports (no recipe)</h2>
		<p class="sub">Loaded with <code>make import</code>. They are not rebuilt by <code>make reset-db</code>. Save a recipe to keep them.</p>
		<ul>
			{#each data.adhoc as o (o.locator)}
				<li><code>{o.locator}</code> · {fmtNum(o.row_count)} features · <Badge value={o.health} /> · imported {fmtAgo(o.imported_at)}</li>
			{/each}
		</ul>
	</section>
{/if}

<style>
	.head h1 { margin: 0 0 0.3rem; font-size: 1.5rem; }
	.head p { margin: 0; color: var(--muted); max-width: 80ch; }
	.bulk { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
	.bulk button { font: inherit; padding: 0.3rem 0.7rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; }
	.filters { display: flex; flex-wrap: wrap; gap: 0.9rem; align-items: end; margin: 1.2rem 0 0.8rem; font-size: 0.82rem; color: var(--muted); }
	.filters label { display: grid; gap: 0.2rem; }
	.filters .check { display: flex; align-items: center; gap: 0.35rem; }
	.filters input[type='search'] { font: inherit; padding: 0.3rem 0.5rem; border: 1px solid var(--border); border-radius: 6px; min-width: 14rem; }
	.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
	table :global(th), td { text-align: left; padding: 0.55rem 0.7rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	table :global(th.num) { text-align: right; }
	table :global(th) { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); background: var(--surface-muted); }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	tr.disabled td { color: var(--muted); }
	.name { font-weight: 600; }
	.sub { font-size: 0.75rem; color: var(--muted); margin-top: 0.1rem; }
	.err { font-size: 0.75rem; color: #8a1c14; }
	.health { display: inline-flex; align-items: center; gap: 0.25rem; font-variant-numeric: tabular-nums; }
	.dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-left: 0.2rem; }
	.dot.ok { background: #1a9850; }
	.dot.warn { background: #e6a100; }
	.dot.fail { background: #c0392b; }
	.proj { display: inline-block; margin-right: 0.4rem; }
	.empty { text-align: center; color: var(--muted); padding: 1.5rem; }
	.adhoc { margin-top: 1.5rem; }
	.adhoc h2 { font-size: 1rem; margin-bottom: 0.2rem; }
</style>
