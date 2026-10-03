<script lang="ts">
	// Run an R or Python analysis process on a published layer (plan Phase 5). The form is built from the process
	// descriptor; the result is an ordinary layer (tipg-vector on pub.analysis_sandbox__job_<id>), previewed in the
	// viewer and added to the Analysis Sandbox map with one click.
	import { onMount } from 'svelte';
	import Viewer from '$lib/components/Viewer.svelte';
	import SortTh from '$lib/admin/SortTh.svelte';
	import { TableSort } from '$lib/admin/sort.svelte';
	import { title as pageTitle } from '$lib/site';
	import type { LayerSpec, ProjectManifest } from '$lib/types';

	let { data } = $props();
	const config = $derived(data.config);

	interface InputSpec {
		type: 'collection-ref' | 'field-ref' | 'enum' | 'integer' | 'number' | 'string';
		title: string;
		description?: string;
		required?: boolean;
		geometry?: string[];
		of?: string;
		dtype?: 'numeric' | 'any';
		values?: string[];
		default?: unknown;
		minimum?: number;
		maximum?: number;
		when?: Record<string, unknown>;
	}
	interface Process {
		id: string;
		runtime: string;
		version: string;
		title: string;
		description: string | null;
		descriptor: { inputs: Record<string, InputSpec> };
		worker_online: boolean;
	}
	interface Field {
		name: string;
		type: string;
		numeric: boolean;
	}
	interface Job {
		id: number;
		process_id: string;
		status: string;
		progress: number | null;
		progress_message: string | null;
		inputs: Record<string, unknown>;
		result: { collection: string; layerSpec: LayerSpec; report: Record<string, unknown>; rows: number } | null;
		error: { message: string; log_tail?: string } | null;
		created_at: string;
	}

	let processes: Process[] = $state([]);
	let processId = $state('');
	let values: Record<string, unknown> = $state({});
	let collections: string[] = $state([]);
	let fieldsByCollection: Record<string, { geometry: string | null; fields: Field[] }> = $state({});
	let inputErrors: { input: string; message: string }[] = $state([]);
	let error = $state('');
	let job = $state<Job | null>(null);
	let recent: Job[] = $state([]);
	const recentSort = new TableSort<Job>({
		job: (j) => j.id,
		process: (j) => j.process_id,
		inputs: (j) => JSON.stringify(j.inputs),
		status: (j) => j.status
	});
	let promoted = $state('');
	let busy = $state(false);

	const proc = $derived(processes.find((p) => p.id === processId));
	const specs = $derived(Object.entries(proc?.descriptor.inputs ?? {}));
	const shown = (spec: InputSpec) => Object.entries(spec.when ?? {}).every(([k, v]) => values[k] === v);
	const running = $derived(job !== null && ['queued', 'running', 'cancel_requested'].includes(job.status));

	async function getJson<T>(path: string): Promise<T> {
		const r = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store' });
		if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${path}`);
		return r.json();
	}

	onMount(() => {
		getJson<Process[]>('/api/admin/processes')
			.then((p) => {
				processes = p;
				if (p.length) pick(p[0].id);
			})
			.catch((e) => (error = e.message));
		getJson<{ collections: { id: string }[] }>(`${config.tilesBase}/collections?f=json`)
			.then((d) => (collections = d.collections.map((c) => c.id).filter((id) => id.startsWith('pub.')).sort()))
			.catch(() => (collections = []));
		loadRecent();
	});

	async function loadRecent() {
		const all = await getJson<(Job & { kind: string })[]>('/api/admin/jobs?limit=50').catch(() => []);
		recent = all.filter((j) => j.kind === 'process').slice(0, 10);
	}

	function pick(id: string) {
		processId = id;
		const p = processes.find((x) => x.id === id);
		values = Object.fromEntries(
			Object.entries(p?.descriptor.inputs ?? {})
				.filter(([, s]) => s.default !== undefined)
				.map(([k, s]) => [k, s.default])
		);
		inputErrors = [];
	}

	async function loadFields(collection: string) {
		if (!collection || fieldsByCollection[collection]) return;
		try {
			fieldsByCollection[collection] = await getJson(`/api/admin/projects/fields?collection=${encodeURIComponent(collection)}`);
		} catch {
			fieldsByCollection[collection] = { geometry: null, fields: [] };
		}
	}

	function setValue(name: string, spec: InputSpec, raw: string) {
		values[name] = spec.type === 'integer' || spec.type === 'number' ? (raw === '' ? undefined : Number(raw)) : raw || undefined;
		if (spec.type === 'collection-ref') {
			loadFields(raw);
			for (const [k, s] of specs) if (s.type === 'field-ref' && s.of === name) values[k] = undefined;
		}
	}

	function fieldChoices(spec: InputSpec): Field[] {
		const info = fieldsByCollection[String(values[spec.of ?? ''] ?? '')];
		return (info?.fields ?? []).filter((f) => spec.dtype !== 'numeric' || f.numeric);
	}

	async function submit() {
		if (!proc) return;
		busy = true;
		error = '';
		inputErrors = [];
		promoted = '';
		try {
			const inputs = Object.fromEntries(
				Object.entries(values).filter(([k, v]) => v !== undefined && v !== '' && shown(proc.descriptor.inputs[k]))
			);
			const r = await fetch('/api/admin/jobs', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ process: processId, inputs })
			});
			const body = await r.json();
			if (r.status === 422) inputErrors = body.detail.errors;
			else if (!r.ok) error = typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`;
			else {
				job = body;
				poll(body.id);
			}
		} finally {
			busy = false;
		}
	}

	function poll(id: number) {
		promoted = '';
		const tick = async () => {
			try {
				job = await getJson<Job>(`/api/admin/jobs/${id}`);
			} catch (e) {
				error = (e as Error).message;
				return;
			}
			if (job && ['queued', 'running', 'cancel_requested'].includes(job.status)) setTimeout(tick, 2000);
			else loadRecent();
		};
		tick();
	}

	async function cancel() {
		if (job) await fetch(`/api/admin/jobs/${job.id}/cancel`, { method: 'POST' });
	}

	async function promote() {
		if (!job) return;
		const r = await fetch(`/api/admin/jobs/${job.id}/promote`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ project: 'analysis-sandbox' })
		});
		if (r.ok) promoted = 'analysis-sandbox';
		else error = `Could not add the layer: HTTP ${r.status}`;
	}

	const preview: ProjectManifest | null = $derived(
		job?.status === 'succeeded' && job.result
			? {
					manifestVersion: 1,
					slug: `job-${job.id}`,
					title: job.result.layerSpec.title,
					status: 'draft',
					view: { center: [-69.25, 45.3], zoom: 6.0, basemap: 'positron' },
					layers: [job.result.layerSpec]
				}
			: null
	);
	const errorFor = (name: string) =>
		inputErrors
			.filter((e) => e.input === name)
			.map((e) => e.message)
			.join('; ');
</script>

<svelte:head><title>{pageTitle('Analysis')}</title></svelte:head>

<h1>Analysis</h1>
<p class="lead">
	Run an R or Python process on a published layer. The result is a new map layer: preview it here, then add it to the
	<a href="/p/analysis-sandbox">Analysis Sandbox</a>.
</p>
{#if error}<p class="err" role="alert">{error}</p>{/if}

<div class="grid">
	<form
		class="card"
		aria-label="Run a process"
		onsubmit={(e) => {
			e.preventDefault();
			submit();
		}}
	>
		<label for="process">Process</label>
		<select id="process" value={processId} onchange={(e) => pick(e.currentTarget.value)}>
			{#each processes as p (p.id)}<option value={p.id}>{p.title} ({p.runtime === 'r' ? 'R' : 'Python'})</option>{/each}
		</select>
		{#if proc}
			<p class="hint">{proc.description}</p>
			{#if !proc.worker_online}
				<p class="err" role="alert">No worker has reported in the last 2 minutes: start one with <code>make workers-up</code>.</p>
			{/if}
			{#each specs as [name, spec] (name)}
				{#if shown(spec)}
					<label for="in-{name}">{spec.title}{spec.required ? '' : ' (optional)'}</label>
					{#if spec.type === 'collection-ref'}
						<select id="in-{name}" value={values[name] ?? ''} onchange={(e) => setValue(name, spec, e.currentTarget.value)}>
							<option value="">Choose a layer…</option>
							{#each collections as c (c)}<option value={c}>{c}</option>{/each}
						</select>
					{:else if spec.type === 'field-ref'}
						<select id="in-{name}" value={values[name] ?? ''} onchange={(e) => setValue(name, spec, e.currentTarget.value)}>
							<option value="">{spec.required ? 'Choose a field…' : 'None'}</option>
							{#each fieldChoices(spec) as f (f.name)}<option value={f.name}>{f.name} ({f.type})</option>{/each}
						</select>
					{:else if spec.type === 'enum'}
						<select id="in-{name}" value={values[name] ?? ''} onchange={(e) => setValue(name, spec, e.currentTarget.value)}>
							{#each spec.values ?? [] as v (v)}<option value={v}>{v}</option>{/each}
						</select>
					{:else}
						<input
							id="in-{name}"
							type={spec.type === 'string' ? 'text' : 'number'}
							step={spec.type === 'integer' ? 1 : 'any'}
							min={spec.minimum}
							max={spec.maximum}
							value={values[name] ?? ''}
							oninput={(e) => setValue(name, spec, e.currentTarget.value)}
						/>
					{/if}
					{#if spec.description}<p class="hint">{spec.description}</p>{/if}
					{#if errorFor(name)}<p class="err" role="alert">{errorFor(name)}</p>{/if}
				{/if}
			{/each}
			<div class="actions">
				<button class="primary" type="submit" disabled={busy || running}>Run</button>
				{#if running}<button type="button" onclick={cancel}>Cancel</button>{/if}
			</div>
		{/if}

		{#if job}
			<section class="job" aria-label="Job status">
				<p>
					<strong>Job {job.id}</strong>: <span class="status {job.status}">{job.status}</span>{job.progress_message
						? ` · ${job.progress_message}`
						: ''}
				</p>
				{#if running}<progress max="1" value={job.progress ?? 0} aria-label="Progress"></progress>{/if}
				{#if job.error}
					<p class="err">{job.error.message}</p>
					{#if job.error.log_tail}<details><summary>Log</summary><pre>{job.error.log_tail}</pre></details>{/if}
				{/if}
				{#if job.result}
					<p>{job.result.rows} features → <code>{job.result.collection}</code></p>
					<details open><summary>Report</summary><pre>{JSON.stringify(job.result.report, null, 2)}</pre></details>
					<button type="button" class="primary" onclick={promote} disabled={!!promoted}>Add to Analysis Sandbox</button>
					{#if promoted}<p role="status">Added. <a href="/p/{promoted}">Open the Analysis Sandbox</a>.</p>{/if}
				{/if}
			</section>
		{/if}
	</form>

	<div class="preview" aria-label="Result preview">
		{#if preview}
			{#key preview.slug}<Viewer manifest={preview} {config} embedded />{/key}
		{:else}
			<p class="placeholder">{running ? 'Running…' : 'Run a process to see its result here.'}</p>
		{/if}
	</div>
</div>

{#if recent.length}
	<section aria-labelledby="recent-h">
		<h2 id="recent-h">Recent analysis jobs</h2>
		<table>
			<thead><tr>
				<SortTh sort={recentSort} key="job">Job</SortTh><SortTh sort={recentSort} key="process">Process</SortTh>
				<SortTh sort={recentSort} key="inputs">Inputs</SortTh><SortTh sort={recentSort} key="status">Status</SortTh>
			</tr></thead>
			<tbody>
				{#each recentSort.apply(recent) as r (r.id)}
					<tr>
						<td><button type="button" class="link" onclick={() => poll(r.id)}>#{r.id}</button></td>
						<td>{r.process_id}</td>
						<td><code>{JSON.stringify(r.inputs)}</code></td>
						<td><span class="status {r.status}">{r.status}</span></td>
					</tr>
				{/each}
			</tbody>
		</table>
	</section>
{/if}

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.4rem; }
	.lead { color: var(--muted); margin: 0 0 1rem; max-width: 75ch; }
	.grid { display: grid; grid-template-columns: minmax(300px, 400px) 1fr; gap: 1.2rem; align-items: start; }
	.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.9rem 1rem; display: grid; gap: 0.3rem; }
	label { font-size: 0.82rem; color: var(--muted); margin-top: 0.4rem; }
	select, input { font: inherit; padding: 0.35rem 0.45rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg, #fff); color: inherit; }
	.hint { font-size: 0.78rem; color: var(--muted); margin: 0.1rem 0 0; }
	.err { color: #b42318; margin: 0.2rem 0; }
	.actions { display: flex; gap: 0.6rem; margin-top: 0.8rem; }
	button { font: inherit; padding: 0.45rem 0.9rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; }
	button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	button.link { border: 0; background: none; padding: 0; color: var(--accent-strong); text-decoration: underline; }
	.job { border-top: 1px solid var(--border); margin-top: 0.8rem; padding-top: 0.6rem; }
	.job p { margin: 0.3rem 0; }
	progress { width: 100%; }
	.status { font-weight: 600; }
	.status.succeeded { color: #1b7837; }
	.status.failed, .status.cancelled { color: #b42318; }
	pre { max-height: 260px; overflow: auto; font-size: 0.75rem; background: #13202c; color: #e6edf3; padding: 0.6rem; border-radius: 8px; }
	.preview { height: 72vh; min-height: 460px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; position: sticky; top: 1rem; }
	.placeholder { display: grid; place-items: center; height: 100%; margin: 0; color: var(--muted); }
	table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 0.5rem; }
	table :global(th), td { text-align: left; padding: 0.35rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	table :global(th.num) { text-align: right; }
	td code { font-size: 0.75rem; word-break: break-all; }
	section h2 { font-size: 1.05rem; margin: 1.5rem 0 0.3rem; }
	@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .preview { position: static; height: 60vh; } }
</style>
