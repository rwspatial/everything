<script lang="ts">
	// Quick map (plan: project-builder §1.7): pick a design, pick a place, get a finished project.
	// core-api builds the manifest from the design (curated layers from the registered projects, a focus
	// mask and outline, framing, titles); this page previews it and saves it like the single-view wizard.
	// A design for parcels ("Parcel site") picks its parcel on a map (ParcelPicker), and saving opens the project
	// workspace, where analyses of the parcel run.
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import ParcelPicker, { type PickedParcel, type PickerTown } from '$lib/admin/ParcelPicker.svelte';
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
				const wanted = page.url.searchParams.get('design');
				if (wanted && !designId && d.some((x) => x.id === wanted)) pickDesign(wanted);
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
	// Parcels: the preview pane is a map to pick from until a parcel is chosen (and again on "Change parcel").
	let picking = $state(true);
	const pickOnMap = $derived(unit === 'parcel' && (picking || !place));
	function pickParcel(p: PickedParcel) {
		place = { key: p.key, name: p.name, short_name: p.short_name, county_name: p.county_name };
		pickedAcres = p.acres;
		picking = false;
	}
	let pickedAcres: number | null = $state(null);
	// Parcels: the town comes first; the map and the address list then show only that town's parcels.
	let parcelTown: PickerTown | null = $state(null);
	let townQuery = $state('');
	let townResults: (Place & { bbox: [number, number, number, number] })[] = $state([]);
	$effect(() => {
		const q = townQuery.trim();
		if (unit !== 'parcel' || q.length < 2) {
			townResults = [];
			return;
		}
		const t = setTimeout(async () => {
			const r = await fetch(`/api/admin/units/town/places?q=${encodeURIComponent(q)}&limit=8`);
			townResults = r.ok ? await r.json() : [];
		}, 200);
		return () => clearTimeout(t);
	});
	function pickTown(t: Place & { bbox: [number, number, number, number] }) {
		parcelTown = { key: t.key, name: t.short_name || t.name, bbox: t.bbox };
		townQuery = '';
		townResults = [];
		place = null;
		picking = true;
		query = '';
	}
	$effect(() => {
		const q = query;
		const u = unit;
		const town = parcelTown;
		if (!u) return;
		if (u === 'parcel' && !town) {
			results = [];
			searchError = '';
			return;
		}
		const t = setTimeout(async () => {
			const within = u === 'parcel' && town ? `&town=${encodeURIComponent(town.key)}` : '';
			const r = await fetch(`/api/admin/units/${u}/places?q=${encodeURIComponent(q)}&limit=12${within}`);
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
		if (!d || !u || !p || (u === 'parcel' && picking)) return;
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
			else {
				saved = { slug: body.slug, version: body.version };
				// A parcel project goes straight to its workspace, where its analyses run.
				if (unit === 'parcel') await goto(`/admin/projects/${body.slug}`);
			}
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>{pageTitle('New project')}</title></svelte:head>

<h1>New project</h1>
<p class="lead">
	Choose a map design and a place: you get a finished, framed map built from the curated layers, ready to save. To
	analyse one property, choose <a href="/admin/new?design=parcel-site">Parcel site analysis</a> and click the parcel on the map. For a
	map of one published view with your own style, use the <a href="/admin/new/view">single-view creator</a>.
</p>
{#if loadError}<p class="error" role="alert">{loadError}</p>{/if}

<div class="builder">
	<div class="steps col-design">
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
	</div>

	<div class="steps col-place">
		<fieldset disabled={!design}>
			<legend>2. Place</legend>
			{#if design && design.geographies.length > 1}
				<div class="units" role="radiogroup" aria-label="Unit">
					{#each design.geographies as g (g)}
						<label><input type="radio" name="unit" value={g} bind:group={unit} onchange={() => (place = null)} /> {units[g]?.title ?? g}</label>
					{/each}
				</div>
			{/if}
			{#if unit === 'parcel'}
				{#if parcelTown}
					<p class="picked">
						Town: <strong>{parcelTown.name}</strong>
						<button type="button" class="link" onclick={() => ((parcelTown = null), (place = null), (picking = true))}>Change town</button>
					</p>
				{:else}
					<label for="town-search">Town</label>
					<input id="town-search" type="search" bind:value={townQuery} placeholder="e.g. Presque Isle" autocomplete="off" />
					<p class="hint">Choose the town first; the map then shows its parcels.</p>
					<ul class="results" aria-label="Towns">
						{#each townResults as t (t.key)}
							<li>
								<button type="button" onclick={() => pickTown(t)}>
									{t.name}{#if t.county_name}<span class="hint">, {t.county_name} County</span>{/if}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
				{#if place && !picking}
					<p class="picked">
						<strong>{place.name}</strong>{#if pickedAcres !== null}<span class="hint">{pickedAcres.toFixed(1)} acres</span>{/if}
						<button type="button" class="link" onclick={() => (picking = true)}>Change parcel</button>
					</p>
				{:else if parcelTown}
					<p class="hint">Click a parcel on the map, or find it by address below.</p>
				{/if}
			{/if}
			{#if unit !== 'parcel' || parcelTown}
			<label for="place-search">{unit === 'parcel' && parcelTown ? `Parcels in ${parcelTown.name}` : `Search ${units[unit]?.plural.toLowerCase() ?? 'places'}`}</label>
			<input id="place-search" type="search" bind:value={query} placeholder={unit === 'town' ? 'e.g. Bethel' : unit === 'county' ? 'e.g. Oxford' : unit === 'parcel' ? 'e.g. 95 Reach Rd' : 'name or GEOID'} autocomplete="off" />
			{#if searchError}<p class="hint">{searchError}</p>{/if}
			<ul class="results" aria-label="Places">
				{#each results as p (p.key)}
					<li>
						<button type="button" class:on={place?.key === p.key} aria-pressed={place?.key === p.key} onclick={() => ((place = p), (picking = false), (pickedAcres = null))}>
							{p.name}{#if p.county_name && unit !== 'county' && unit !== 'parcel'}<span class="hint">, {p.county_name} County</span>{/if}
						</button>
					</li>
				{/each}
			</ul>
			{/if}
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
		{#if pickOnMap}
			<ParcelPicker tilesBase={config.tilesBase} town={parcelTown} selected={place?.key ?? null} onpick={pickParcel} />
		{:else if final}
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
	/* Three columns: 1. design, 2. place (and save), 3. the map. */
	.builder { display: grid; grid-template-columns: minmax(250px, 310px) minmax(260px, 320px) 1fr; gap: 1rem; align-items: start; }
	.col-design .designs { max-height: calc(80vh - 3rem); overflow: auto; padding-right: 0.2rem; }
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
	.picked { margin: 0.2rem 0; font-size: 0.88rem; display: flex; flex-wrap: wrap; gap: 0.2rem 0.5rem; align-items: baseline; }
	.link { all: unset; cursor: pointer; color: var(--accent-strong); text-decoration: underline; font-size: 0.82rem; }
	.link:focus-visible { outline: 2px solid var(--accent); }
	.saved { background: #e8f4ea; border: 1px solid #3c8a4a; border-radius: 8px; padding: 0.6rem 0.8rem; margin-top: 0.4rem; }
	.preview { height: 80vh; min-height: 520px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; position: sticky; top: 1rem; }
	.placeholder { display: grid; place-items: center; height: 100%; margin: 0; color: var(--muted); }
	@media (max-width: 1200px) {
		.builder { grid-template-columns: minmax(250px, 320px) 1fr; }
		.preview { grid-column: 1 / -1; position: static; height: 70vh; }
		.col-design .designs { max-height: none; }
	}
	@media (max-width: 760px) {
		.builder { grid-template-columns: 1fr; }
		.preview { height: 60vh; }
	}
</style>
