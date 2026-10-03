<script lang="ts">
	// Dataset actions (admin plan Phase B): each button queues a job that the dataset worker runs with
	// scripts/geoimport.py. Progress is polled; when the job ends the page data is reloaded.
	import { invalidateAll } from '$app/navigation';
	import { onDestroy } from 'svelte';
	import Badge from './Badge.svelte';
	import { ACTIVE_STATES, AdminApiError, api, fmtBytes, fmtNum, post, type ActiveJob, type JobDetail } from './api';

	let { name, enabled, kind, active }: { name: string; enabled: boolean; kind: string; active: ActiveJob[] } = $props();

	const ACTIONS = [
		{ id: 'freshness', label: 'Check for updates', help: 'Ask the source whether a newer version exists.' },
		{ id: 'dry_run', label: 'Dry run', help: 'What an import would download and replace. Changes nothing.' },
		{ id: 'import', label: 'Re-import', help: 'Rebuild the table from the cached download (ArcGIS and Census sources are fetched again).' },
		{ id: 'redownload', label: 'Re-download and import', help: 'Fetch the source again, then rebuild the table.' },
		{ id: 'healthcheck', label: 'Re-check health', help: 'Check the table, its published views and their tiles.' }
	] as const;
	const LABEL: Record<string, string> = { set_enabled: 'Enable / disable', ...Object.fromEntries(ACTIONS.map((a) => [a.id, a.label])) };

	let job = $state<JobDetail | null>(null);
	let message = $state('');
	let error = $state('');
	let timer: ReturnType<typeof setTimeout> | undefined;
	onDestroy(() => clearTimeout(timer));

	const running = $derived(job !== null && ACTIVE_STATES.includes(job.status));
	const busyElsewhere = $derived(!job && active.length > 0);

	$effect(() => {
		// A job that was already queued (by the scheduler, the CLI or another tab): follow it.
		if (!job && active.length) follow(active[0].id);
	});

	async function follow(id: number) {
		clearTimeout(timer);
		try {
			job = await api<JobDetail>(fetch, `/jobs/${id}`);
		} catch (e) {
			error = (e as Error).message;
			return;
		}
		if (ACTIVE_STATES.includes(job.status)) {
			timer = setTimeout(() => follow(id), 2000);
		} else {
			message = job.status === 'succeeded' ? `${LABEL[job.action] ?? job.action}: done` : '';
			await invalidateAll();
		}
	}

	async function run(action: string) {
		error = '';
		message = '';
		if (action === 'redownload' && !confirm(`Download ${name} again from its source and rebuild the table?`)) return;
		try {
			const j = await post<JobDetail>(fetch, `/datasets/${encodeURIComponent(name)}/actions`, { action });
			if (j.deduplicated) message = `Already queued (job #${j.id}); following it.`;
			follow(j.id);
		} catch (e) {
			error = e instanceof AdminApiError ? e.message : String(e);
		}
	}

	async function cancel() {
		if (job) await post(fetch, `/jobs/${job.id}/cancel`).catch((e) => (error = (e as Error).message));
	}

	const plan = $derived(job?.status === 'succeeded' ? (job.result?.plan as Record<string, unknown> | undefined) : undefined);
</script>

<div class="actions" role="group" aria-label="Dataset actions">
	{#each ACTIONS as a (a.id)}
		<button
			type="button"
			onclick={() => run(a.id)}
			disabled={running || busyElsewhere || (!enabled && (a.id === 'import' || a.id === 'redownload'))}
			title={a.help}>{a.label}</button
		>
	{/each}
	<button type="button" class="toggle" onclick={() => run(enabled ? 'disable' : 'enable')} disabled={running || busyElsewhere}>
		{enabled ? 'Disable' : 'Enable'}
	</button>
</div>
<p class="hint">
	{#if kind === 'raster'}Raster rebuilds run one at a time.{/if}
	Jobs are run by the dataset worker (<code>make workers-up</code>); every run appears in the history above.
</p>

{#if job}
	<div class="job" role="status" aria-live="polite">
		<Badge value={job.status} />
		<strong>{LABEL[job.action] ?? job.action}</strong>
		<span class="sub"
			>job #{job.id}{job.attempts > 1 ? `, attempt ${job.attempts} of ${job.max_attempts}` : ''}{job.progress_message
				? ` · ${job.progress_message}`
				: ''}</span
		>
		{#if running}<button type="button" onclick={cancel} disabled={job.status === 'cancel_requested'}>Cancel</button>{/if}
		{#if job.run_id}<a href="/admin/runs/{job.run_id}">run log</a>{/if}
	</div>
	{#if job.error && !running}<p class="err" role="alert">{job.error.message}</p>{/if}
{/if}
{#if message}<p class="ok">{message}</p>{/if}
{#if error}<p class="err" role="alert">{error}</p>{/if}

{#if plan}
	<table class="plan" aria-label="Dry run">
		<tbody>
			<tr><th scope="row">Would</th><td>{plan.would}</td></tr>
			{#if plan.source}<tr><th scope="row">Source</th><td class="break">{plan.source}</td></tr>{/if}
			{#if plan.upstream_bytes !== undefined}<tr
					><th scope="row">Upstream file</th><td
						>{fmtBytes(plan.upstream_bytes as number)}{plan.upstream_version ? ` · ${plan.upstream_version}` : ''}</td
					></tr
				>{/if}
			{#if plan.cached_bytes !== undefined}<tr
					><th scope="row">Cached copy</th><td
						>{plan.cached_bytes ? fmtBytes(plan.cached_bytes as number) : 'none'}{plan.cached_version ? ` · ${plan.cached_version}` : ''}</td
					></tr
				>{/if}
			{#if plan.upstream_features !== undefined}<tr><th scope="row">Upstream features</th><td>{fmtNum(plan.upstream_features as number)}</td></tr>{/if}
			<tr><th scope="row">Replaces</th><td>{plan.target} · {fmtNum(plan.current_rows as number)} rows now</td></tr>
			{#if plan.upstream_error}<tr><th scope="row">Source error</th><td class="err">{plan.upstream_error}</td></tr>{/if}
		</tbody>
	</table>
{/if}

<style>
	.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
	button { font: inherit; font-size: 0.85rem; padding: 0.35rem 0.75rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; }
	button:hover:not(:disabled) { border-color: var(--accent); }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.toggle { margin-left: auto; }
	.hint, .sub { font-size: 0.8rem; color: var(--muted); }
	.job { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-top: 0.6rem; }
	.ok { color: #1b7837; margin: 0.4rem 0 0; }
	.err { color: #b42318; margin: 0.4rem 0 0; }
	.plan { margin-top: 0.6rem; border-collapse: collapse; font-size: 0.85rem; }
	.plan th { text-align: left; font-weight: 500; color: var(--muted); padding: 0.2rem 1rem 0.2rem 0; vertical-align: top; }
	.plan td { padding: 0.2rem 0; }
	.break { word-break: break-all; }
</style>
