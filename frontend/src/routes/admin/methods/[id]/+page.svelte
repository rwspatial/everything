<script lang="ts">
	import Tex from '$lib/admin/Tex.svelte';
	import { fmtNum } from '$lib/admin/api';

	let { data } = $props();
	const m = $derived(data.m);
	// Methods with manual edits (settlements): how many, and how they change the result.
	let editStats: { settlements: number; edited_settlements: number; edits: Record<string, number> } | null = $state(null);
	$effect(() => {
		if (!m.editor) return;
		fetch('/api/admin/settlement-edits', { cache: 'no-store' })
			.then((r) => (r.ok ? r.json() : null))
			.then((fc) => (editStats = fc?.stats ?? null))
			.catch(() => (editStats = null));
	});
	const when = (s: string | null) => (s ? new Date(s).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : 'never');
</script>

<svelte:head><title>{m.title} · Methods · Admin</title></svelte:head>

<p class="crumb"><a href="/admin/methods">Methods</a></p>
<h1>{m.title}</h1>
<p class="lead">{m.summary}</p>
{#if m.project}
	<p class="sub">
		Project <a href="/admin/projects">{m.project}</a>{#if m.layer}, layer <code>{m.layer}</code>{/if}
		· <a href="/p/{m.project}">open the map</a>
	</p>
{/if}

{#if m.editor}
	<p class="edit-cta">
		<a class="btn" href={m.editor}>Edit settlements</a>
		{#if editStats}
			<span class="sub">
				{Object.values(editStats.edits).reduce((a, b) => a + b, 0)} manual edits
				({['replace', 'add', 'remove'].map((k) => `${editStats!.edits[k] ?? 0} ${k}`).join(', ')}) ·
				{editStats.edited_settlements} edited settlements
			</span>
		{/if}
	</p>
{/if}

{#if m.live.length}
	<section class="cards" aria-label="Current output">
		{#each m.live as o (o.collection)}
			{#if o.error}
				<div class="card bad"><code>{o.collection}</code><span>{o.error}</span></div>
			{:else}
				<div class="card"><span class="big">{fmtNum(o.rows)}</span><span>rows in <code>{o.collection}</code></span></div>
				{#each Object.entries(o.sums ?? {}) as [field, v] (field)}
					<div class="card"><span class="big">{fmtNum(v === null ? null : Math.round(v))}</span><span>total <code>{field}</code></span></div>
				{/each}
			{/if}
		{/each}
	</section>
{/if}

{#if m.runs}
	{@const r = m.runs}
	<p class="sub">
		Analysis process <code>{r.process}</code>{#if r.version}{' '}v{r.version}{/if} · {r.worker_online ? 'worker online' : 'no worker running'} · run it
		from a parcel project's workspace (<a href="/admin/new?design=parcel-site">new parcel project</a>)
	</p>
	<section class="cards" aria-label="Usage">
		<div class="card"><span class="big">{fmtNum(r.succeeded)}</span><span>successful runs{#if r.failed} ({r.failed} failed){/if}</span></div>
		<div class="card"><span class="big">{fmtNum(r.places)}</span><span>parcels analysed</span></div>
		<div class="card"><span class="big">{r.mean_score === null ? '–' : Math.round(r.mean_score)}</span><span>mean score</span></div>
		<div class="card"><span class="big small">{when(r.last_run)}</span><span>last run</span></div>
	</section>
	{#if r.classes.length}
		<p class="sub">Results by class: {r.classes.map((c) => `${c.class} ${c.n}`).join(' · ')}</p>
	{/if}
	{#if r.recent.length}
		<h2>Recent runs</h2>
		<div class="table-wrap">
			<table>
				<thead><tr><th>Job</th><th>Parcel</th><th>Result</th><th>Finished</th></tr></thead>
				<tbody>
					{#each r.recent as j (j.id)}
						<tr>
							<td class="val">{j.id}</td>
							<td>{#if j.project}<a href="/admin/projects/{j.project}">{j.name ?? j.place}</a>{:else}{j.name ?? j.place}{/if}</td>
							<td>{#if j.status === 'succeeded'}{j.score} · {j.class}{:else}{j.status}{#if j.error} <span class="sub">{j.error.split('\n')[0]}</span>{/if}{/if}</td>
							<td>{when(j.finished_at)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/if}

<h2>Inputs</h2>
<ul class="inputs">
	{#each m.inputs as i (i.name)}<li><code>{i.name}</code>: {i.role}</li>{/each}
</ul>

<h2>Steps</h2>
<ol class="steps">
	{#each m.steps as s (s.title)}
		<li>
			<strong>{s.title}</strong>
			<p>{s.detail}</p>
			{#if s.math}<Tex tex={s.math} />{/if}
		</li>
	{/each}
</ol>

<h2>Parameters</h2>
<div class="table-wrap">
	<table>
		<thead><tr><th>Parameter</th><th>Value</th><th>Why</th></tr></thead>
		<tbody>
			{#each m.parameters as p (p.name)}
				<tr>
					<td>{p.name}</td>
					<td class="val">{p.value}</td>
					<td>{p.why}{#if p.math}<Tex tex={p.math} />{/if}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>

{#if m.caveats.length}
	<h2>Caveats</h2>
	<ul class="caveats">{#each m.caveats as c (c)}<li>{c}</li>{/each}</ul>
{/if}

{#if m.references?.length}
	<h2>References</h2>
	<ul class="caveats">
		{#each m.references as r (r.title)}<li>{#if r.url}<a href={r.url} rel="noopener noreferrer" target="_blank">{r.title}</a>{:else}{r.title}{/if}{#if r.note}: {r.note}{/if}</li>{/each}
	</ul>
{/if}

{#if m.code_text}
	<details>
		<summary>Code: <code>{m.code}</code></summary>
		<pre><code>{m.code_text}</code></pre>
	</details>
{/if}

{#if m.sql_text}
	<details>
		<summary>SQL: <code>{m.sql}</code></summary>
		<pre><code>{m.sql_text}</code></pre>
	</details>
{/if}

<style>
	.crumb { margin: 0 0 0.3rem; font-size: 0.85rem; }
	.edit-cta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.8rem; margin: 0.8rem 0 0; }
	.btn { padding: 0.4rem 0.85rem; border-radius: 6px; font-weight: 600; text-decoration: none; background: var(--accent); color: #fff; font-size: 0.9rem; }
	.btn:hover { background: var(--accent-strong); color: #fff; }
	h1 { margin: 0 0 0.3rem; font-size: 1.5rem; }
	h2 { font-size: 1rem; margin: 1.4rem 0 0.5rem; }
	.lead { color: var(--muted); margin: 0; max-width: 75ch; }
	.sub { font-size: 0.8rem; color: var(--muted); }
	.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.8rem; margin: 1rem 0 0.4rem; }
	.card { background: var(--surface); border: 1px solid var(--border); border-left-width: 4px; border-radius: 10px; padding: 0.7rem 0.9rem; display: grid; gap: 0.15rem; font-size: 0.85rem; color: var(--muted); }
	.card.bad { border-left-color: #b42318; }
	.big.small { font-size: 1rem; }
	.big { font-size: 1.4rem; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
	.inputs, .caveats { margin: 0; padding-left: 1.2rem; display: grid; gap: 0.3rem; max-width: 85ch; font-size: 0.9rem; }
	.steps { margin: 0; padding-left: 1.4rem; display: grid; gap: 0.7rem; max-width: 85ch; }
	.steps p { margin: 0.2rem 0 0; font-size: 0.9rem; }
	.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
	th, td { text-align: left; padding: 0.5rem 0.65rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	th { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); background: var(--surface-muted); }
	.val { white-space: nowrap; font-variant-numeric: tabular-nums; font-weight: 600; }
	details { margin-top: 1.4rem; }
	summary { cursor: pointer; font-weight: 600; font-size: 0.95rem; }
	pre { background: var(--surface-muted); border: 1px solid var(--border); border-radius: 8px; padding: 0.8rem; overflow-x: auto; font-size: 0.78rem; line-height: 1.45; }
	code { font-size: 0.8rem; }
</style>
