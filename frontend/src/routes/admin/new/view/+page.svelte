<script lang="ts">
	import Viewer from '$lib/components/Viewer.svelte';
	import {
		buildStyle,
		geomKind,
		PRESET_FIELD,
		PRESET_LABELS,
		presetsFor,
		type FieldStats,
		type Preset
	} from '$lib/presets';
	import { title as pageTitle } from '$lib/site';
	import type { LayerSpec, ProjectManifest } from '$lib/types';

	let { data } = $props();
	const config = $derived(data.config);

	interface Collection {
		id: string;
		title?: string;
		description?: string;
		extent?: { spatial?: { bbox?: number[][] } };
	}
	interface Field {
		name: string;
		type: string;
		numeric: boolean;
	}
	interface Issue {
		code: string;
		path: string;
		message: string;
		level: string;
	}
	interface Report {
		ok: boolean;
		errors: Issue[];
		warnings: Issue[];
		checked: string[];
	}

	// ---- 1. source ----------------------------------------------------------------------------------
	let collections: Collection[] = $state([]);
	let loadError = $state('');
	let collectionId = $state('');
	let fields: Field[] = $state([]);
	let geometry: string | null = $state(null);

	$effect(() => {
		fetch(`${config.tilesBase}/collections?f=json`)
			.then((r) => r.json())
			.then((d: { collections: Collection[] }) => {
				collections = d.collections.filter((c) => c.id.startsWith('pub.')).sort((a, b) => a.id.localeCompare(b.id));
			})
			.catch((e) => (loadError = `Could not list tiPG collections: ${e.message}`));
	});

	const collection = $derived(collections.find((c) => c.id === collectionId));

	async function pickCollection(id: string) {
		collectionId = id;
		fields = [];
		geometry = null;
		field = '';
		stats = null;
		report = null;
		saved = null;
		if (!id) return;
		const r = await fetch(`/api/admin/projects/fields?collection=${encodeURIComponent(id)}`);
		if (!r.ok) {
			loadError = r.status === 404 ? `${id} is not a view (functions need a hand-written manifest)` : `fields: HTTP ${r.status}`;
			return;
		}
		loadError = '';
		const d = await r.json();
		fields = d.fields;
		geometry = d.geometry;
		const name = id.replace(/^pub\./, '').split('__').pop() ?? 'layer';
		layerId = name.replace(/_/g, '-');
		layerTitle = (collection?.title && collection.title !== id ? collection.title : name.replace(/_/g, ' ')).replace(/^\w/, (c) => c.toUpperCase());
		popupField = fields.find((f) => ['name', 'namelsad', 'title'].includes(f.name))?.name ?? '';
		if (!presetsFor(geomKind(geometry)).includes(preset)) preset = 'single';
	}

	// ---- 2. style --------------------------------------------------------------------------------------
	let preset: Preset = $state('single');
	let field = $state('');
	let color = $state('#0072B2');
	let stats: FieldStats | null = $state(null);
	let statsError = $state('');
	const g = $derived(geomKind(geometry));
	const needs = $derived(PRESET_FIELD[preset]);
	const fieldChoices = $derived(needs === 'numeric' || needs === 'optional-numeric' ? fields.filter((f) => f.numeric) : fields);

	$effect(() => {
		// Fetch breaks / categories whenever the field or preset changes.
		const f = field;
		const c = collectionId;
		stats = null;
		statsError = '';
		if (!c || !f || needs === 'none') return;
		fetch(`/api/admin/projects/stats?collection=${encodeURIComponent(c)}&field=${encodeURIComponent(f)}&k=5`)
			.then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
			.then((s: FieldStats) => (stats = s))
			.catch((e) => (statsError = `Could not compute statistics: ${e.message}`));
	});

	// ---- 3. project ------------------------------------------------------------------------------------
	let projectTitle = $state('');
	let slugEdited = $state(false);
	let slugInput = $state('');
	let layerId = $state('layer');
	let layerTitle = $state('');
	let popupField = $state('');
	const slugify = (s: string) =>
		s
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-+|-+$/g, '')
			.slice(0, 48);
	const slug = $derived(slugEdited ? slugInput : slugify(projectTitle));

	function view(): ProjectManifest['view'] {
		const b = collection?.extent?.spatial?.bbox?.[0];
		if (b && b.length >= 4 && b.every((x) => Number.isFinite(x)) && b[2] - b[0] < 180) {
			const r = (x: number) => Math.round(x * 1e4) / 1e4;
			return {
				center: [r((b[0] + b[2]) / 2), r((b[1] + b[3]) / 2)],
				zoom: 6.3,
				bounds: [r(b[0]), r(b[1]), r(b[2]), r(b[3])],
				basemap: 'positron'
			};
		}
		return { center: [-69.25, 45.3], zoom: 6.3, basemap: 'positron' }; // Maine
	}

	const manifest: ProjectManifest | null = $derived.by(() => {
		if (!collectionId || !fields.length) return null;
		const built = buildStyle(preset, g, field || null, stats, color, layerTitle || layerId);
		const props = [...new Set([popupField, field].filter(Boolean))];
		const layer: LayerSpec = {
			id: slugify(layerId) || 'layer',
			title: layerTitle || layerId,
			source: { type: 'tipg-vector', collection: collectionId, ...(props.length ? { properties: props } : {}) },
			style: built.style,
			legend: built.legend,
			interaction: {
				...(popupField
					? { popup: { template: field && field !== popupField ? `{${popupField}}: {${field}}` : `{${popupField}}` } }
					: {}),
				inspect: true
			}
		};
		return {
			manifestVersion: 1,
			slug: slug || 'new-project',
			title: projectTitle || 'New project',
			status: 'draft',
			description: collection?.description ?? '',
			tags: ['maine'],
			view: view(),
			layers: [layer]
		};
	});
	const manifestJson = $derived(manifest ? JSON.stringify(manifest, null, 2) : '');

	// Rebuilding the map on every keystroke is wasteful: the preview follows the manifest with a short delay.
	let preview: ProjectManifest | null = $state(null);
	let previewKey = $state('');
	$effect(() => {
		const m = manifest;
		const json = manifestJson;
		const t = setTimeout(() => {
			preview = m;
			previewKey = json;
		}, 400);
		return () => clearTimeout(t);
	});

	// ---- 4. validate + save -------------------------------------------------------------------------------
	let report: Report | null = $state(null);
	let busy = $state(false);
	let saved: { slug: string; version: number } | null = $state(null);
	let saveError = $state('');

	async function send(path: string, method = 'POST') {
		busy = true;
		saveError = '';
		try {
			const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: manifestJson });
			const body = await r.json().catch(() => ({}));
			if (r.status === 422) report = body.detail as Report;
			else if (!r.ok) saveError = typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`;
			return { ok: r.ok, body };
		} finally {
			busy = false;
		}
	}

	async function validate() {
		const res = await send('/api/admin/projects/validate');
		if (res.ok) report = res.body as Report;
	}

	async function save() {
		saved = null;
		const res = await send('/api/admin/projects');
		if (res.ok) {
			report = res.body.report as Report;
			saved = { slug: res.body.slug, version: res.body.version };
		}
	}
</script>

<svelte:head><title>{pageTitle('New project')}</title></svelte:head>

<h1>New project: one published view</h1>
<p class="lead">
	Pick a published view, choose a style, check the preview, save. (For a finished map of a place, use the <a href="/admin/new">design-based creator</a>.) The wizard writes the same manifest as
	<code>./mapgen new</code>; after saving, <code>./mapgen export &lt;slug&gt;</code> puts it in git.
</p>

<div class="wizard">
	<form class="steps" onsubmit={(e) => e.preventDefault()}>
		<fieldset>
			<legend>1. Data</legend>
			<label for="collection">Published view (tiPG collection)</label>
			<select id="collection" value={collectionId} onchange={(e) => pickCollection(e.currentTarget.value)}>
				<option value="">Choose a view…</option>
				{#each collections as c (c.id)}<option value={c.id}>{c.id}</option>{/each}
			</select>
			{#if loadError}<p class="error" role="alert">{loadError}</p>{/if}
			{#if geometry}<p class="hint">{fields.length} fields, geometry {geometry}</p>{/if}
		</fieldset>

		<fieldset disabled={!fields.length}>
			<legend>2. Style</legend>
			<label for="preset">Preset</label>
			<select id="preset" bind:value={preset}>
				{#each presetsFor(g) as p (p)}<option value={p}>{PRESET_LABELS[p]}</option>{/each}
			</select>
			{#if needs !== 'none'}
				<label for="field">Field{needs === 'optional-numeric' ? ' (optional weight)' : ''}</label>
				<select id="field" bind:value={field}>
					<option value="">{needs === 'optional-numeric' ? 'None' : 'Choose a field…'}</option>
					{#each fieldChoices as f (f.name)}<option value={f.name}>{f.name} ({f.type})</option>{/each}
				</select>
				{#if statsError}<p class="error" role="alert">{statsError}</p>{/if}
				{#if stats?.kind === 'numeric'}<p class="hint">range {stats.min} to {stats.max}; breaks {stats.breaks?.join(', ')}</p>{/if}
			{/if}
			{#if preset === 'single' || preset === 'graduated-circle'}
				<label for="color">Colour</label>
				<input id="color" type="color" bind:value={color} />
			{/if}
			<label for="popup">Popup label field</label>
			<select id="popup" bind:value={popupField}>
				<option value="">No popup</option>
				{#each fields as f (f.name)}<option value={f.name}>{f.name}</option>{/each}
			</select>
		</fieldset>

		<fieldset disabled={!fields.length}>
			<legend>3. Project</legend>
			<label for="ptitle">Project title</label>
			<input id="ptitle" bind:value={projectTitle} placeholder="e.g. Maine Public Lands" />
			<label for="slug">Slug (URL and folder name)</label>
			<input
				id="slug"
				value={slug}
				oninput={(e) => {
					slugEdited = true;
					slugInput = e.currentTarget.value;
				}}
				pattern="[a-z0-9]+(-[a-z0-9]+)*"
			/>
			<label for="ltitle">Layer title</label>
			<input id="ltitle" bind:value={layerTitle} />
		</fieldset>

		<div class="actions">
			<button type="button" onclick={validate} disabled={!manifest || busy}>Validate</button>
			<button type="button" class="primary" onclick={save} disabled={!manifest || !projectTitle || busy}>Save project</button>
		</div>

		{#if saveError}<p class="error" role="alert">{saveError}</p>{/if}
		{#if saved}
			<div class="saved" role="status">
				Saved <strong>{saved.slug}</strong> (version {saved.version}).
				<a href="/p/{saved.slug}">Open the map</a>. To keep it in git: <code>./mapgen export {saved.slug}</code>
			</div>
		{/if}
		{#if report}
			<section class="report" aria-label="Validation report">
				<p class={report.ok ? 'ok' : 'error'}>
					{report.ok ? 'Valid' : 'Not valid'}: {report.errors.length} error(s), {report.warnings.length} warning(s)
					<span class="hint">(checked {report.checked.join(', ')})</span>
				</p>
				<ul>
					{#each [...report.errors, ...report.warnings] as i (i.code + i.path)}
						<li class={i.level}><code>{i.code}</code> {i.path}: {i.message}</li>
					{/each}
				</ul>
			</section>
		{/if}

		{#if manifest}
			<details>
				<summary>Manifest JSON</summary>
				<pre>{manifestJson}</pre>
			</details>
		{/if}
	</form>

	<div class="preview" aria-label="Preview">
		{#if preview}
			{#key previewKey}
				<Viewer manifest={preview} {config} embedded />
			{/key}
		{:else}
			<p class="placeholder">Choose a view to see a live preview.</p>
		{/if}
	</div>
</div>

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.4rem; }
	.lead { color: var(--muted); margin: 0 0 1rem; max-width: 70ch; }
	.wizard { display: grid; grid-template-columns: minmax(300px, 380px) 1fr; gap: 1.2rem; align-items: start; }
	.steps { display: grid; gap: 0.9rem; }
	fieldset { border: 1px solid var(--border); border-radius: 10px; padding: 0.6rem 0.9rem 0.9rem; display: grid; gap: 0.3rem; background: var(--surface); }
	legend { font-weight: 600; padding: 0 0.3rem; }
	label { font-size: 0.82rem; color: var(--muted); margin-top: 0.35rem; }
	select, input:not([type='color']) { font: inherit; padding: 0.35rem 0.45rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg, #fff); color: inherit; }
	.actions { display: flex; gap: 0.6rem; }
	button { font: inherit; padding: 0.45rem 0.9rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); cursor: pointer; }
	button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
	button:disabled { opacity: 0.5; cursor: not-allowed; }
	.hint { font-size: 0.78rem; color: var(--muted); margin: 0.2rem 0 0; }
	.error { color: #b42318; }
	.ok { color: #1b7837; }
	.report ul { margin: 0.3rem 0 0; padding-left: 1.1rem; font-size: 0.82rem; }
	.report li.warning { color: var(--muted); }
	.saved { background: #e8f4ea; border: 1px solid #3c8a4a; border-radius: 8px; padding: 0.6rem 0.8rem; }
	pre { max-height: 320px; overflow: auto; font-size: 0.75rem; background: #13202c; color: #e6edf3; padding: 0.6rem; border-radius: 8px; }
	.preview { height: 78vh; min-height: 480px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; position: sticky; top: 1rem; }
	.placeholder { display: grid; place-items: center; height: 100%; margin: 0; color: var(--muted); }
	@media (max-width: 900px) {
		.wizard { grid-template-columns: 1fr; }
		.preview { position: static; height: 60vh; }
	}
</style>
