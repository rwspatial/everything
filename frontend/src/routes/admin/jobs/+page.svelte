<script lang="ts">
	import { onMount } from 'svelte';
	import Badge from '$lib/admin/Badge.svelte';
	import SortTh from '$lib/admin/SortTh.svelte';
	import { TableSort } from '$lib/admin/sort.svelte';
	import { api, fmtAgo, fmtBytes, fmtDuration, fmtNum, post, type Job, type RunSummary } from '$lib/admin/api';

	let jobs = $state<Job[]>([]);
	let recent = $state<RunSummary[]>([]);
	let error = $state<string | null>(null);
	let updated = $state<Date | null>(null);
	const sort = new TableSort<RunSummary>({
		run: (r) => r.id,
		dataset: (r) => r.recipe_name,
		action: (r) => r.action,
		status: (r) => r.status,
		when: (r) => r.finished_at ?? r.started_at,
		duration: (r) => r.seconds,
		rows: (r) => r.rows_written,
		downloaded: (r) => r.bytes_downloaded,
		by: (r) => r.triggered_by
	});

	async function load() {
		try {
			[jobs, recent] = await Promise.all([api<Job[]>(fetch, '/jobs?limit=50'), api<RunSummary[]>(fetch, '/runs?limit=50')]);
			updated = new Date();
			error = null;
		} catch (e) {
			error = (e as Error).message;
		}
	}

	onMount(() => {
		load();
		const t = setInterval(load, 5000); // live status by polling (plan decision 5)
		return () => clearInterval(t);
	});

	async function cancel(id: number) {
		await post(fetch, `/jobs/${id}/cancel`).catch((e) => (error = (e as Error).message));
		load();
	}

	const active = $derived(jobs.filter((j) => ['queued', 'running', 'cancel_requested'].includes(j.status)));
</script>

<svelte:head><title>Jobs &amp; runs · Admin</title></svelte:head>

<h1>Jobs &amp; runs</h1>
<p class="lead">
	Every download, import and check, whether started from the CLI (<code>make import-recipe …</code>), from a dataset's
	Actions, or by the dataset worker's scheduler (update checks on each recipe's schedule, daily health checks). Refreshes every 5 s{updated ? `; last update ${updated.toLocaleTimeString()}` : ''}.
</p>
{#if error}<p class="err" role="alert">{error}</p>{/if}

<section aria-labelledby="active-h">
	<h2 id="active-h">Active jobs ({active.length})</h2>
	{#if active.length}
		<ul class="active">
			{#each active as j (j.id)}
				<li>
					<Badge value={j.status} /> #{j.id} {j.action}
					{#if j.recipe_name}<a href="/admin/datasets/{j.recipe_name}">{j.recipe_name}</a>{/if}
					· {j.locked_by ?? 'waiting'}{j.progress_message ? ` · ${j.progress_message}` : ''} · heartbeat {fmtAgo(j.heartbeat_at)}
					{#if !(j.locked_by ?? '').startsWith('inline@') && j.status !== 'cancel_requested'}
						<button type="button" class="cancel" onclick={() => cancel(j.id)}>Cancel</button>
					{/if}
				</li>
			{/each}
		</ul>
	{:else}
		<p class="sub">Nothing running.</p>
	{/if}
</section>

<section aria-labelledby="runs-h">
	<h2 id="runs-h">Recent runs</h2>
	<div class="table-wrap">
		<table>
			<thead>
				<tr>
					<SortTh {sort} key="run">Run</SortTh><SortTh {sort} key="dataset">Dataset</SortTh><SortTh {sort} key="action">Action</SortTh>
					<SortTh {sort} key="status">Status</SortTh><SortTh {sort} key="when">When</SortTh><SortTh {sort} key="duration">Duration</SortTh>
					<SortTh {sort} key="rows" class="num">Rows</SortTh><SortTh {sort} key="downloaded" class="num">Downloaded</SortTh><SortTh {sort} key="by">By</SortTh>
				</tr>
			</thead>
			<tbody>
				{#each sort.apply(recent) as r (r.id)}
					<tr>
						<td><a href="/admin/runs/{r.id}">#{r.id}</a></td>
						<td>{#if r.recipe_name}<a href="/admin/datasets/{r.recipe_name}">{r.recipe_name}</a>{:else}<span class="sub">ad hoc</span>{/if}</td>
						<td>{r.action}</td>
						<td><Badge value={r.status} />{#if r.outcome}<div class="sub">{r.outcome}</div>{/if}</td>
						<td>{fmtAgo(r.finished_at ?? r.started_at)}</td>
						<td>{fmtDuration(r.seconds)}</td>
						<td class="num">{fmtNum(r.rows_written)}</td>
						<td class="num">{fmtBytes(r.bytes_downloaded)}</td>
						<td>{r.triggered_by}</td>
					</tr>
				{:else}
					<tr><td colspan="9" class="sub">{updated ? 'No runs yet.' : 'Loading…'}</td></tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.5rem; }
	h2 { font-size: 1rem; margin: 1.3rem 0 0.5rem; }
	.lead { color: var(--muted); margin: 0; }
	.active { padding-left: 1.1rem; font-size: 0.85rem; }
	.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
	table :global(th), td { text-align: left; padding: 0.5rem 0.65rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	table :global(th.num) { text-align: right; }
	table :global(th) { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); background: var(--surface-muted); }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.sub { font-size: 0.75rem; color: var(--muted); }
	.err { background: #fde3e1; color: #8a1c14; padding: 0.5rem 0.8rem; border-radius: 8px; }
	.cancel { font: inherit; font-size: 0.8rem; padding: 0.1rem 0.5rem; margin-left: 0.4rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; }
</style>
