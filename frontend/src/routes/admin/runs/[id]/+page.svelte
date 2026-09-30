<script lang="ts">
	import Badge from '$lib/admin/Badge.svelte';
	import { fmtBytes, fmtDate, fmtDuration, fmtNum } from '$lib/admin/api';

	let { data } = $props();
	const r = $derived(data.run);
</script>

<svelte:head><title>Run #{r.id} · Admin</title></svelte:head>

<p class="crumbs">
	{#if r.recipe_name}<a href="/admin/datasets/{r.recipe_name}">← {r.recipe_name}</a> · {/if}<a href="/admin/jobs">Jobs &amp; runs</a>
</p>

<h1>Run #{r.id} <Badge value={r.status} /></h1>

<dl class="facts">
	<dt>Dataset</dt><dd>{r.recipe_name ?? 'ad hoc (no recipe)'}</dd>
	<dt>Action</dt><dd>{r.action}{r.outcome ? `: ${r.outcome}` : ''}</dd>
	<dt>Triggered by</dt><dd>{r.triggered_by}{r.host ? ` on ${r.host}` : ''}</dd>
	<dt>Started</dt><dd>{fmtDate(r.started_at)}</dd>
	<dt>Finished</dt><dd>{fmtDate(r.finished_at)}</dd>
	<dt>Duration</dt><dd>{fmtDuration(r.seconds)}</dd>
	<dt>Rows written</dt><dd>{fmtNum(r.rows_written)}</dd>
	<dt>Downloaded</dt><dd>{fmtBytes(r.bytes_downloaded)}</dd>
	<dt>Job</dt><dd>{r.job_id ? `#${r.job_id} (${r.job_status}, created by ${r.job_created_by})` : '–'}</dd>
	<dt>Parameters</dt><dd><code>{JSON.stringify(r.params)}</code></dd>
</dl>

{#if r.error}
	<h2>Error</h2>
	<pre class="error">{r.error}</pre>
{/if}

<h2>Log <span class="sub">(last 16 KB, secrets redacted)</span></h2>
{#if r.log_tail}<pre>{r.log_tail}</pre>{:else}<p class="sub">No log captured for this run.</p>{/if}

<style>
	.crumbs { margin: 0 0 0.5rem; font-size: 0.85rem; }
	h1 { font-size: 1.4rem; display: flex; align-items: center; gap: 0.6rem; }
	h2 { font-size: 1rem; margin: 1.2rem 0 0.4rem; }
	.facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.3rem 1rem; font-size: 0.85rem; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.9rem 1rem; }
	dt { color: var(--muted); }
	dd { margin: 0; word-break: break-word; }
	pre { background: #13202c; color: #e6edf3; padding: 0.8rem 1rem; border-radius: 8px; overflow: auto; font-size: 0.78rem; max-height: 32rem; white-space: pre-wrap; }
	pre.error { background: #3b1512; }
	.sub { font-size: 0.75rem; color: var(--muted); font-weight: 400; }
</style>
