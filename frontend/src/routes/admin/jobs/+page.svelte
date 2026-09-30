<script lang="ts">
	import { onMount } from 'svelte';
	import Badge from '$lib/admin/Badge.svelte';
	import { api, fmtAgo, fmtBytes, fmtDuration, fmtNum, type Job, type RunSummary } from '$lib/admin/api';

	let jobs = $state<Job[]>([]);
	let recent = $state<RunSummary[]>([]);
	let error = $state<string | null>(null);
	let updated = $state<Date | null>(null);

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

	const active = $derived(jobs.filter((j) => ['queued', 'running', 'cancel_requested'].includes(j.status)));
</script>

<svelte:head><title>Jobs &amp; runs · Admin</title></svelte:head>

<h1>Jobs &amp; runs</h1>
<p class="lead">
	Every download and import, whether started from the CLI (<code>make import-recipe …</code>) or, from Phase B, from this
	dashboard. Refreshes every 5 s{updated ? `; last update ${updated.toLocaleTimeString()}` : ''}.
</p>
{#if error}<p class="err" role="alert">{error}</p>{/if}

<section aria-labelledby="active-h">
	<h2 id="active-h">Active jobs ({active.length})</h2>
	{#if active.length}
		<ul class="active">
			{#each active as j (j.id)}
				<li><Badge value={j.status} /> #{j.id} {j.action} {j.recipe_name ?? ''} · {j.locked_by ?? 'waiting'} · heartbeat {fmtAgo(j.heartbeat_at)}</li>
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
				<tr><th scope="col">Run</th><th scope="col">Dataset</th><th scope="col">Action</th><th scope="col">Status</th><th scope="col">When</th><th scope="col">Duration</th><th scope="col" class="num">Rows</th><th scope="col" class="num">Downloaded</th><th scope="col">By</th></tr>
			</thead>
			<tbody>
				{#each recent as r (r.id)}
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
	th, td { text-align: left; padding: 0.5rem 0.65rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	th { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); background: var(--surface-muted); }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.sub { font-size: 0.75rem; color: var(--muted); }
	.err { background: #fde3e1; color: #8a1c14; padding: 0.5rem 0.8rem; border-radius: 8px; }
</style>
