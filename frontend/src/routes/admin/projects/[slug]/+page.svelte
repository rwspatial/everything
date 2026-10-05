<script lang="ts">
	// Project workspace (admin): the project's map, and the analyses that run on the one place it is about
	// (manifest `place`, e.g. a parcel from the "Parcel site" design). Running one queues a job on that place; when it
	// succeeds its layer goes on the map (replacing the previous result of the same analysis) and its report shows here.
	import { onDestroy } from 'svelte';
	import Viewer from '$lib/components/Viewer.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import type { AnalysisRun, PlaceProcess, ProjectAnalyses } from '$lib/admin/api';
	import { REPORTS } from '$lib/admin/reports';
	import { placeOf } from '$lib/projects';
	import type { ProjectManifest } from '$lib/types';

	let { data } = $props();
	const config = $derived(data.config);
	// Writable deriveds: reset when the page's data changes (another project), updated locally after a run.
	let manifest: ProjectManifest = $derived(data.manifest);
	let analyses: ProjectAnalyses | null = $derived(data.analyses);
	let mapVersion = $state(0);
	let error = $state('');

	const runsOf = (p: PlaceProcess) => (analyses?.runs ?? []).filter((r) => r.process_id === p.id);
	const active = (r: AnalysisRun) => r.status === 'queued' || r.status === 'running' || r.status === 'cancel_requested';
	const latestDone = (p: PlaceProcess) => runsOf(p).find((r) => r.status === 'succeeded');
	const current = (p: PlaceProcess) => runsOf(p).find(active);
	const lastFailed = (p: PlaceProcess) => {
		const r = runsOf(p)[0];
		return r && r.status === 'failed' ? r : undefined;
	};

	// Runs that had finished when the page opened are left as they are; a run finishing from now on goes on the map.
	const handled = $derived(new Set<number>((data.analyses?.runs ?? []).filter((r: AnalysisRun) => r.status === 'succeeded').map((r: AnalysisRun) => r.id)));

	async function loadAnalyses() {
		const r = await fetch(`/api/admin/projects/${data.slug}/analyses`, { cache: 'no-store' });
		if (r.ok) analyses = await r.json();
	}

	async function refresh() {
		await loadAnalyses();
		for (const p of analyses?.processes ?? []) {
			const done = latestDone(p);
			if (done && !done.on_map && !handled.has(done.id)) {
				handled.add(done.id);
				await addToMap(done.id);
			}
		}
	}

	async function addToMap(jobId: number) {
		error = '';
		const r = await fetch(`/api/admin/projects/${data.slug}/analyses/${jobId}/add`, { method: 'POST' });
		if (!r.ok) {
			const body = await r.json().catch(() => ({}));
			error = typeof body.detail === 'string' ? body.detail : `Could not add the result to the map (HTTP ${r.status})`;
			return;
		}
		const m = await fetch(`/api/projects/${data.slug}`, { cache: 'no-store' });
		if (m.ok) {
			manifest = await m.json();
			mapVersion += 1;
		}
		await loadAnalyses();
	}

	async function run(p: PlaceProcess) {
		error = '';
		const r = await fetch(`/api/admin/projects/${data.slug}/analyses`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ process: p.id })
		});
		if (!r.ok) {
			const body = await r.json().catch(() => ({}));
			error =
				typeof body.detail === 'string'
					? body.detail
					: (body.detail?.errors?.map((e: { message: string }) => e.message).join('; ') ?? `HTTP ${r.status}`);
			return;
		}
		await refresh();
	}

	// Poll while anything is queued or running.
	let timer: ReturnType<typeof setInterval> | undefined;
	$effect(() => {
		const busy = (analyses?.runs ?? []).some(active);
		if (busy && !timer) timer = setInterval(refresh, 2000);
		if (!busy && timer) {
			clearInterval(timer);
			timer = undefined;
		}
	});
	onDestroy(() => timer && clearInterval(timer));

	const when = (s: string | null) => (s ? new Date(s).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : '');
</script>

<svelte:head><title>{manifest.title} · Workspace · Admin</title></svelte:head>

<p class="crumb"><a href="/admin/projects">Projects</a></p>
<header class="head">
	<div>
		<h1>{manifest.title}</h1>
		{#if placeOf(manifest)}{@const pl = placeOf(manifest)!}<p class="sub">{pl.name ?? analyses?.place.name ?? pl.key} · {pl.unit}</p>{/if}
	</div>
	<div class="actions">
		<StatusBadge status={manifest.status} />
		<a href="/p/{data.slug}">Open the map</a>
	</div>
</header>

<div class="workspace">
	<div class="map">
		{#key mapVersion}
			<Viewer {manifest} {config} embedded />
		{/key}
	</div>

	<section class="panel" aria-labelledby="analyses-title">
		<h2 id="analyses-title">Analyses</h2>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
		{#if !analyses}
			<p class="hint">
				This project is not about one place, so there is nothing to analyse here. Build one from a design, e.g.
				<a href="/admin/new?design=parcel-site">Parcel site analysis</a>.
			</p>
		{:else if !analyses.processes.length}
			<p class="hint">No analyses run on a {analyses.place.unit} yet.</p>
		{:else}
			{#each analyses.processes as p (p.id)}
				{@const now = current(p)}
				{@const done = latestDone(p)}
				{@const failed = lastFailed(p)}
				<article class="analysis" aria-label={p.title}>
					<div class="a-head">
						<h3>{p.title}</h3>
						<button type="button" class="primary" onclick={() => run(p)} disabled={!!now || !p.worker_online}>
							{now ? 'Running…' : done ? 'Run again' : 'Run'}
						</button>
					</div>
					<p class="desc">{p.description}</p>
					<p class="meta">
						{#if p.method}<a href="/admin/methods/{p.method}">How it works</a> · {/if}version {p.version}
						{#if !p.worker_online}<span class="warn"> · no analysis worker is running (make workers-up)</span>{/if}
					</p>
					{#if now}
						<div class="progress" role="status" aria-live="polite">
							<progress max="1" value={now.progress ?? 0} aria-label="Progress"></progress>
							<span>{now.progress_message ?? now.status}</span>
						</div>
					{/if}
					{#if failed && !now}<p class="error">Last run failed: {failed.error?.split('\n')[0]}</p>{/if}
					{#if done && !done.on_map && !now}
						<p class="meta">The latest result is not on the map. <button type="button" class="link" onclick={() => addToMap(done.id)}>Put it on the map</button></p>
					{/if}

					{#if done && done.report && REPORTS[p.id]}
						{@const Report = REPORTS[p.id]}
						<Report run={done} />
					{:else if done && done.report}
						<details open>
							<summary>Latest result ({when(done.finished_at)})</summary>
							<pre>{JSON.stringify(done.report, null, 2)}</pre>
						</details>
					{/if}

					{#if runsOf(p).length > 1}
						<details class="history">
							<summary>Earlier runs ({runsOf(p).length - 1})</summary>
							<ul>
								{#each runsOf(p).slice(1) as r (r.id)}
									<li>
										Job {r.id} · {r.status}{#if r.report && typeof r.report.score === 'number'} · {r.report.score} ({r.report.class}){/if} · {when(r.finished_at ?? r.created_at)}
										{#if r.status === 'succeeded' && !r.on_map}<button type="button" class="link" onclick={() => addToMap(r.id)}>Put on the map</button>{/if}
									</li>
								{/each}
							</ul>
						</details>
					{/if}
				</article>
			{/each}
		{/if}
	</section>
</div>

<style>
	.crumb { margin: 0 0 0.3rem; font-size: 0.85rem; }
	.head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 0.5rem 1rem; margin-bottom: 0.8rem; }
	h1 { margin: 0; font-size: 1.4rem; }
	.sub { margin: 0.15rem 0 0; color: var(--muted); font-size: 0.85rem; }
	.actions { display: flex; align-items: center; gap: 0.8rem; font-size: 0.9rem; }
	.workspace { display: grid; grid-template-columns: 1fr minmax(340px, 440px); gap: 1rem; align-items: start; }
	.map { height: 78vh; min-height: 520px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; position: sticky; top: 1rem; }
	.panel { display: grid; gap: 0.8rem; }
	h2 { margin: 0; font-size: 1.05rem; }
	.analysis { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.8rem 0.9rem; display: grid; gap: 0.4rem; }
	.a-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
	h3 { margin: 0; font-size: 1rem; }
	.desc { margin: 0; font-size: 0.84rem; color: var(--muted); }
	.meta { margin: 0; font-size: 0.78rem; color: var(--muted); }
	.warn { color: #9a6700; }
	.primary { font: inherit; font-size: 0.85rem; padding: 0.35rem 0.8rem; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; }
	.primary:disabled { opacity: 0.55; cursor: not-allowed; }
	.progress { display: flex; align-items: center; gap: 0.5rem; font-size: 0.8rem; color: var(--muted); }
	.progress progress { flex: 1; accent-color: var(--accent); }
	.error { color: #b42318; font-size: 0.84rem; margin: 0; }
	.hint { color: var(--muted); font-size: 0.78rem; font-weight: 400; }
	.history { font-size: 0.8rem; }
	.history ul { margin: 0.3rem 0 0; padding-left: 1.1rem; display: grid; gap: 0.2rem; }
	.link { all: unset; cursor: pointer; color: var(--accent-strong); text-decoration: underline; margin-left: 0.4rem; }
	pre { font-size: 0.72rem; background: var(--surface-muted); padding: 0.5rem; border-radius: 6px; overflow-x: auto; }
	@media (max-width: 1000px) {
		.workspace { grid-template-columns: 1fr; }
		.map { position: static; height: 60vh; }
	}
</style>
