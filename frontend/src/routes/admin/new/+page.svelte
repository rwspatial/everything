<script lang="ts">
	// Quick map (plan: project-builder §1.7): pick a design, pick a place, get a finished project.
	// core-api builds the manifest from the design (curated layers from the registered projects, a focus
	// mask and outline, framing, titles); this page previews it and saves it like the single-view wizard.
	import Viewer from '$lib/components/Viewer.svelte';
	import { title as pageTitle } from '$lib/site';
	import type { ProjectManifest } from '$lib/types';

	let { data } = $props();
	const config = $derived(data.config);

	interface Design {
		id: string;
		title: string;
		description: string;
		geographies: string[];
	}
	interface Unit {
		id: string;
		title: string;
		plural: string;
		unit_count: number;
	}
	interface Place {
		key: string;
		name: string;
		short_name: string;
		county_name: string | null;
	}
	interface Issue {
		code: string;
		path: string;
		message: string;
	}
	interface Report {
		ok: boolean;
		errors: Issue[];
		warnings: Issue[];
	}

	let designs: Design[] = $state([]);
	let units: Record<string, Unit> = $state({});
	let loadError = $state('');
	$effect(() => {
		Promise.all([fetch('/api/admin/designs').then((r) => r.json()), fetch('/api/admin/units').then((r) => r.json())])
			.then(([d, u]: [Design[], Unit[]]) => {
				designs = d;
				units = Object.fromEntries(u.map((x) => [x.id, x]));
			})
			.catch((e) => (loadError = `Could not load designs: ${e.message}`));
	});

	// ---- 1. design ---------------------------------------------------------------------------------------
	let designId = $state('');
	const design = $derived(designs.find((d) => d.id === designId));
	let unit = $state('');
	function pickDesign(id: string) {
		designId = id;
		const d = designs.find((x) => x.id === id);
		if (d && !d.geographies.includes(unit)) {
			unit = d.geographies[0];
			place = null;
		}
	}

	// ---- 2. place --------------------------------------------------------------------------------------------
	let query = $state('');
	let results: Place[] = $state([]);
	let place: Place | null = $state(null);
	let searchError = $state('');
	$effect(() => {
		const q = query;
		const u = unit;
		if (!u) return;
		const t = setTimeout(async () => {
			const r = await fetch(`/api/admin/units/${u}/places?q=${encodeURIComponent(q)}&limit=12`);
			const body = await r.json().catch(() => []);
			searchError = r.ok ? '' : typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`;
			results = r.ok ? body : [];
		}, 200);
		return () => clearTimeout(t);
	});

	// ---- 3. build, preview, save ---------------------------------------------------------------------------
	let manifest: ProjectManifest | null = $state(null);
	let report: Report | null = $state(null);
	let building = $state(false);
	let buildError = $state('');
	let projectTitle = $state('');
	let slug = $state('');
	$effect(() => {
		const d = designId;
		const u = unit;
		const p = place;
		manifest = null;
		report = null;
		saved = null;
		if (!d || !u || !p) return;
		building = true;
		buildError = '';
		fetch(`/api/admin/designs/${d}/manifest`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ unit: u, place: p.key })
		})
			.then(async (r) => {
				const body = await r.json();
				if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`);
				manifest = body.manifest;
				report = body.report;
				projectTitle = body.manifest.title;
				slug = body.manifest.slug;
			})
			.catch((e) => (buildError = e.message))
			.finally(() => (building = false));
	});
	const final: ProjectManifest | null = $derived.by(() => {
		const m = manifest as ProjectManifest | null;
		return m ? { ...m, title: projectTitle || m.title, slug } : null;
	});

	let busy = $state(false);
	let saved: { slug: string; version: number } | null = $state(null);
	let saveError = $state('');
	async function save() {
		if (!final) return;
		busy = true;
		saveError = '';
		try {
			const r = await fetch('/api/admin/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(final, null, 2) });
			const body = await r.json().catch(() => ({}));
			if (r.status === 422) report = body.detail as Report;
			else if (!r.ok) saveError = typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`;
			else saved = { slug: body.slug, version: body.version };
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>{pageTitle('New project')}</title></svelte:head>

<h1>New project</h1>
<p class="lead">
	Choose a map design and a place: you get a finished, framed map built from the curated layers, ready to save. For a
	map of one published view with your own style, use the <a href="/admin/new/view">single-view creator</a>.
</p>
{#if loadError}<p class="error" role="alert">{loadError}</p>{/if}

<div class="builder">
	<div class="steps">
		<fieldset>
			<legend>1. Design</legend>
			<div class="designs" role="radiogroup" aria-label="Map design">
				{#each designs as d (d.id)}
					<button type="button" role="radio" aria-checked={d.id === designId} class="design" class:on={d.id === designId} onclick={() => pickDesign(d.id)}>
						<strong>{d.title}</strong>
						<span class="for">For a {d.geographies.map((g) => units[g]?.title.toLowerCase() ?? g).join(' or ')}</span>
						<span class="desc">{d.description}</span>
					</button>
				{/each}
			</div>
		</fieldset>

		<fieldset disabled={!design}>
			<legend>2. Place</legend>
			{#if design && design.geographies.length > 1}
				<div class="units" role="radiogroup" aria-label="Unit">
					{#each design.geographies as g (g)}
						<label><input type="radio" name="unit" value={g} bind:group={unit} onchange={() => (place = null)} /> {units[g]?.title ?? g}</label>
					{/each}
				</div>
			{/if}
			<label for="place-search">Search {units[unit]?.plural.toLowerCase() ?? 'places'}</label>
			<input id="place-search" type="search" bind:value={query} placeholder={unit === 'town' ? 'e.g. Bethel' : unit === 'county' ? 'e.g. Oxford' : 'name or GEOID'} autocomplete="off" />
			{#if searchError}<p class="hint">{searchError}</p>{/if}
			<ul class="results" aria-label="Places">
				{#each results as p (p.key)}
					<li>
						<button type="button" class:on={place?.key === p.key} aria-pressed={place?.key === p.key} onclick={() => (place = p)}>
							{p.name}{#if p.county_name && unit !== 'county'}<span class="hint">, {p.county_name} County</span>{/if}
						</button>
					</li>
				{/each}
			</ul>
		</fieldset>

		<fieldset disabled={!manifest}>
			<legend>3. Save</legend>
			<label for="ptitle">Project title</label>
			<input id="ptitle" bind:value={projectTitle} maxlength="80" />
			<label for="slug">Slug (URL and folder name)</label>
			<input id="slug" bind:value={slug} pattern="[a-z0-9]+(-[a-z0-9]+)*" />
			<button type="button" class="primary" onclick={save} disabled={!final || busy || !report?.ok}>Save project</button>
			{#if building}<p class="hint">Building the map…</p>{/if}
			{#if buildError}<p class="error" role="alert">{buildError}</p>{/if}
			{#if saveError}<p class="error" role="alert">{saveError}</p>{/if}
			{#if report && !report.ok}
				<ul class="issues">{#each report.errors as i (i.code + i.path)}<li><code>{i.code}</code> {i.path}: {i.message}</li>{/each}</ul>
			{/if}
			{#if saved}
				<div class="saved" role="status">
					Saved <strong>{saved.slug}</strong>. <a href="/p/{saved.slug}">Open the map</a>. To keep it in git:
					<code>./mapgen export {saved.slug}</code>
				</div>
			{/if}
		</fieldset>
	</div>

	<div class="preview" aria-label="Preview">
		{#if final}
			{#key manifest}
				<Viewer manifest={final} {config} embedded />
			{/key}
		{:else}
			<p class="placeholder">{design ? 'Choose a place to see the map.' : 'Choose a design to start.'}</p>
		{/if}
	</div>
</div>

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.4rem; }
	.lead { color: var(--muted); margin: 0 0 1rem; max-width: 75ch; }
	.builder { display: grid; grid-template-columns: minmax(320px, 400px) 1fr; gap: 1.2rem; align-items: start; }
	.steps { display: grid; gap: 0.9rem; }
	fieldset { border: 1px solid var(--border); border-radius: 10px; padding: 0.6rem 0.9rem 0.9rem; display: grid; gap: 0.35rem; background: var(--surface); }
	fieldset:disabled { opacity: 0.6; }
	legend { font-weight: 600; padding: 0 0.3rem; }
	label { font-size: 0.82rem; color: var(--muted); margin-top: 0.3rem; }
	input:not([type='radio']) { font: inherit; padding: 0.35rem 0.45rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg, #fff); color: inherit; }
	.designs { display: grid; gap: 0.45rem; }
	.design { all: unset; cursor: pointer; display: grid; gap: 0.15rem; padding: 0.55rem 0.7rem; border: 1px solid var(--border); border-radius: 8px; background: var(--bg, #fff); }
	.design:hover { border-color: var(--accent); }
	.design:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
	.design.on { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
	.design .for { font-size: 0.75rem; color: var(--accent); }
	.design .desc { font-size: 0.78rem; color: var(--muted); }
	.units { display: flex; gap: 1rem; }
	.units label { margin: 0; color: inherit; font-size: 0.88rem; }
	.results { list-style: none; margin: 0.2rem 0 0; padding: 0; max-height: 15rem; overflow: auto; border: 1px solid var(--border); border-radius: 6px; }
	.results:empty { display: none; }
	.results button { all: unset; cursor: pointer; display: block; width: 100%; box-sizing: border-box; padding: 0.35rem 0.55rem; font-size: 0.88rem; }
	.results button:hover, .results button.on { background: var(--surface-muted); }
	.results button.on { font-weight: 600; }
	.results button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
	button.primary { font: inherit; margin-top: 0.6rem; padding: 0.45rem 0.9rem; border-radius: 6px; border: 1px solid var(--accent); background: var(--accent); color: #fff; cursor: pointer; justify-self: start; }
	button.primary:disabled { opacity: 0.5; cursor: not-allowed; }
	.hint { font-size: 0.78rem; color: var(--muted); margin: 0.2rem 0 0; }
	.error { color: #b42318; }
	.issues { margin: 0.3rem 0 0; padding-left: 1.1rem; font-size: 0.82rem; color: #b42318; }
	.saved { background: #e8f4ea; border: 1px solid #3c8a4a; border-radius: 8px; padding: 0.6rem 0.8rem; margin-top: 0.4rem; }
	.preview { height: 80vh; min-height: 520px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; position: sticky; top: 1rem; }
	.placeholder { display: grid; place-items: center; height: 100%; margin: 0; color: var(--muted); }
	@media (max-width: 900px) {
		.builder { grid-template-columns: 1fr; }
		.preview { position: static; height: 60vh; }
	}
</style>
