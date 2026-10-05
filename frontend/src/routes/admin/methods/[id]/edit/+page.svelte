<script lang="ts">
	// Settlement editor (plan: classification §1): draw polygons over the computed settlements to replace an outline,
	// add a settlement the method missed, or mark an area as not a settlement; name it and set its size class.
	// core-api stores the edit and re-applies all edits (src_units.apply_settlement_edits()); the map then reloads.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { Map as MlMap, NavigationControl, type GeoJSONSource } from 'maplibre-gl';
	import { TerraDraw, TerraDrawPolygonMode, TerraDrawRenderMode } from 'terra-draw';
	import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';
	import '$lib/maplibre';
	import { resolveBasemap } from '$lib/basemaps';

	type Action = 'replace' | 'add' | 'remove';
	interface EditProps {
		id: number;
		action: Action;
		name: string | null;
		settlement_class: string | null;
		note: string | null;
		created_by: string;
		updated_at: string;
	}
	interface Edit {
		type: 'Feature';
		id: number;
		geometry: GeoJSON.MultiPolygon;
		properties: EditProps;
	}
	interface Stats {
		settlements: number;
		edited_settlements: number;
		computed: number;
		edits: Partial<Record<Action, number>>;
	}

	const ACTIONS: { id: Action; label: string; help: string; color: string }[] = [
		{ id: 'replace', label: 'Replace outline', help: 'The drawn outline becomes the settlement; computed shapes inside it are cut away.', color: '#2a78d6' },
		{ id: 'add', label: 'Add settlement', help: 'A settlement the method missed; computed shapes it overlaps merge into it.', color: '#1baf7a' },
		{ id: 'remove', label: 'Not a settlement', help: 'Computed settlements inside it are removed (campgrounds, industrial parks…).', color: '#e34948' }
	];
	const CLASSES = ['City', 'Town', 'Suburb', 'Village', 'Hamlet', 'Roadside strip'];
	const actionOf = (a: Action) => ACTIONS.find((x) => x.id === a)!;

	const config = $derived(page.data.config);
	const isSettlements = $derived(page.params.id === 'settlements');

	let container = $state<HTMLDivElement>();
	let map: MlMap | undefined;
	let draw: TerraDraw | undefined;
	let edits: Edit[] = $state([]);
	let stats: Stats | null = $state(null);
	let error = $state('');
	let busy = $state(false);
	let tilesVersion = 0;

	// What the form is working on: a new drawing (geometry, no id) or a saved edit (id), and its fields.
	let drawing: Action | null = $state(null);
	let form: { id: number | null; action: Action; name: string; settlement_class: string; note: string; geometry: GeoJSON.Polygon | null } | null =
		$state(null);

	async function api(path: string, init?: RequestInit) {
		const r = await fetch(`/api/admin/settlement-edits${path}`, { headers: { 'Content-Type': 'application/json' }, ...init });
		const body = await r.json().catch(() => ({}));
		if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`);
		return body;
	}

	async function load() {
		const fc = await api('');
		edits = fc.features;
		stats = fc.stats;
		(map?.getSource('edits') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: edits });
	}

	/** The settlements changed on the server: reload their tiles (a new URL, so no cached tile is reused). */
	function reloadSettlements() {
		tilesVersion += 1;
		const src = map?.getSource('settlements') as { setTiles?: (t: string[]) => void } | undefined;
		src?.setTiles?.([settlementTiles()]);
	}
	const settlementTiles = () =>
		`${config.tilesBase}/collections/pub.maine_places__settlements/tiles/WebMercatorQuad/{z}/{x}/{y}?properties=town,settlement_class,source,buildings&v=${tilesVersion}`;

	function startDrawing(a: Action) {
		error = '';
		form = null;
		drawing = a;
		draw?.clear();
		draw?.setMode('polygon');
	}
	function stopDrawing() {
		drawing = null;
		draw?.clear();
		draw?.setMode('render');
	}

	function edit(e: Edit) {
		stopDrawing();
		form = { id: e.id, action: e.properties.action, name: e.properties.name ?? '', settlement_class: e.properties.settlement_class ?? '', note: e.properties.note ?? '', geometry: null };
		zoomTo(e);
	}
	function zoomTo(e: Edit) {
		const xs: number[] = [];
		const ys: number[] = [];
		for (const poly of e.geometry.coordinates) for (const [x, y] of poly[0]) (xs.push(x), ys.push(y));
		map?.fitBounds([Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)], { padding: 80, maxZoom: 16, duration: 600 });
	}
	/** Redraw a saved edit's outline: the next finished polygon replaces its geometry. */
	function redraw() {
		if (!form) return;
		drawing = form.action;
		draw?.clear();
		draw?.setMode('polygon');
	}

	async function save() {
		if (!form) return;
		busy = true;
		error = '';
		const properties = { action: form.action, name: form.name || null, settlement_class: form.settlement_class || null, note: form.note || null };
		try {
			const body =
				form.id === null
					? await api('', { method: 'POST', body: JSON.stringify({ type: 'Feature', geometry: form.geometry, properties }) })
					: await api(`/${form.id}`, {
							method: 'PUT',
							body: JSON.stringify({ type: 'Feature', geometry: form.geometry ?? undefined, properties })
						});
			stats = body.stats;
			form = null;
			stopDrawing();
			await load();
			reloadSettlements();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	async function remove(id: number) {
		if (!confirm(`Delete edit #${id}? The computed settlements come back where it was.`)) return;
		busy = true;
		try {
			stats = (await api(`/${id}`, { method: 'DELETE' })).stats;
			if (form?.id === id) form = null;
			await load();
			reloadSettlements();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	// Town search: fly there.
	let townQuery = $state('');
	let towns: { key: string; name: string; county_name: string | null; bbox: [number, number, number, number] }[] = $state([]);
	$effect(() => {
		const q = townQuery.trim();
		if (q.length < 2) {
			towns = [];
			return;
		}
		const t = setTimeout(async () => {
			const r = await fetch(`/api/admin/units/town/places?q=${encodeURIComponent(q)}&limit=6`);
			towns = r.ok ? await r.json() : [];
		}, 200);
		return () => clearTimeout(t);
	});

	onMount(() => {
		if (page.params.id !== 'settlements') return;
		let disposed = false;
		(async () => {
			const bm = await resolveBasemap('positron');
			if (disposed || !container) return;
			map = new MlMap({ container, style: bm.style, center: [-70.25, 43.68], zoom: 12, attributionControl: { compact: true } });
			map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
			map.on('load', async () => {
				const m = map!;
				m.addSource('buildings', {
					type: 'vector',
					tiles: [`${config.tilesBase}/collections/pub.maine_places__buildings/tiles/WebMercatorQuad/{z}/{x}/{y}?properties=id`],
					minzoom: 13,
					maxzoom: 16
				});
				m.addSource('settlements', { type: 'vector', tiles: [settlementTiles()], minzoom: 5, maxzoom: 16 });
				m.addSource('edits', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
				m.addLayer({ id: 'settlements-fill', type: 'fill', source: 'settlements', 'source-layer': 'default', paint: { 'fill-color': '#f2a93b', 'fill-opacity': 0.35 } });
				m.addLayer({ id: 'buildings', type: 'fill', source: 'buildings', 'source-layer': 'default', minzoom: 13, paint: { 'fill-color': '#7d8590', 'fill-opacity': 0.7 } });
				m.addLayer({
					id: 'settlements-line',
					type: 'line',
					source: 'settlements',
					'source-layer': 'default',
					paint: {
						'line-color': ['match', ['get', 'source'], 'edited', '#7a3e00', '#c77d0a'],
						'line-width': ['match', ['get', 'source'], 'edited', 2.2, 1.2]
					}
				});
				const byAction = ['match', ['get', 'action'], ...ACTIONS.flatMap((a) => [a.id, a.color]), '#888'] as unknown as string;
				m.addLayer({ id: 'edits-fill', type: 'fill', source: 'edits', paint: { 'fill-color': byAction, 'fill-opacity': 0.12 } });
				m.addLayer({ id: 'edits-line', type: 'line', source: 'edits', paint: { 'line-color': byAction, 'line-width': 2, 'line-dasharray': [3, 2] } });
				m.on('click', 'edits-fill', (ev) => {
					if (drawing) return;
					const id = Number(ev.features?.[0]?.properties?.id);
					const e = edits.find((x) => x.id === id);
					if (e) edit(e);
				});
				m.on('mouseenter', 'edits-fill', () => (m.getCanvas().style.cursor = drawing ? '' : 'pointer'));
				m.on('mouseleave', 'edits-fill', () => (m.getCanvas().style.cursor = ''));

				draw = new TerraDraw({
					adapter: new TerraDrawMapLibreGLAdapter({ map: m }),
					modes: [new TerraDrawPolygonMode(), new TerraDrawRenderMode({ modeName: 'render', styles: {} })]
				});
				draw.start();
				draw.setMode('render');
				draw.on('finish', (id) => {
					const f = draw!.getSnapshotFeature(id);
					if (!f || f.geometry.type !== 'Polygon' || !drawing) return;
					const geometry = f.geometry as GeoJSON.Polygon;
					if (form && form.id !== null) form = { ...form, geometry };
					else form = { id: null, action: drawing, name: '', settlement_class: '', note: '', geometry };
					drawing = null;
					draw!.setMode('render');
				});
				// For tests: the editor's map and drawing tool.
				(window as unknown as { __settlementEditor?: unknown }).__settlementEditor = { map: m, draw };
				try {
					await load();
				} catch (e) {
					error = (e as Error).message;
				}
			});
		})();
		return () => {
			disposed = true;
			draw?.stop();
			map?.remove();
		};
	});
</script>

<svelte:head><title>Edit settlements · Methods &amp; sources · Admin</title></svelte:head>

<p class="crumb"><a href="/admin/methods">Methods &amp; sources</a> › <a href="/admin/methods/settlements">Settlements</a></p>
{#if !isSettlements}
	<h1>Not editable</h1>
	<p class="hint">Only the settlements method has manual edits.</p>
{:else}
	<header class="head">
		<div>
			<h1>Edit settlements</h1>
			<p class="sub">
				Draw where the method got it wrong. Edits are applied on top of the computed outlines, so they survive rebuilds.
				{#if stats}<span class="stats" role="status">{stats.settlements.toLocaleString()} settlements ({stats.edited_settlements} edited) from {stats.computed.toLocaleString()} computed</span>{/if}
			</p>
		</div>
		<a href="/p/maine-places">Open the Maine Places map</a>
	</header>

	<div class="editor">
		<div class="map-wrap">
			<div class="map" bind:this={container} aria-label="Settlement map: draw an edit" role="application"></div>
			<div class="toolbar" role="toolbar" aria-label="Draw an edit">
				{#each ACTIONS as a (a.id)}
					<button type="button" class:on={drawing === a.id} style:--c={a.color} aria-pressed={drawing === a.id} onclick={() => startDrawing(a.id)} title={a.help}>
						<i></i>{a.label}
					</button>
				{/each}
				{#if drawing}<button type="button" class="cancel" onclick={stopDrawing}>Cancel</button>{/if}
			</div>
			{#if drawing}
				<p class="hint-pill" role="status">Click to add corners; double-click (or click the first corner) to finish.</p>
			{/if}
			<div class="town">
				<label class="visually-hidden" for="se-town">Go to a town</label>
				<input id="se-town" type="search" placeholder="Go to a town…" bind:value={townQuery} autocomplete="off" />
				{#if towns.length}
					<ul aria-label="Towns">
						{#each towns as t (t.key)}
							<li><button type="button" onclick={() => (map?.fitBounds(t.bbox, { padding: 24, duration: 600 }), (townQuery = ''))}>{t.name}</button></li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>

		<section class="panel" aria-label="Edits">
			{#if error}<p class="error" role="alert">{error}</p>{/if}
			{#if form}
				<form
					class="form"
					aria-label={form.id === null ? 'New edit' : `Edit #${form.id}`}
					onsubmit={(e) => {
						e.preventDefault();
						save();
					}}
				>
					<h2>{form.id === null ? 'New edit' : `Edit #${form.id}`}</h2>
					<fieldset>
						<legend>Action</legend>
						{#each ACTIONS as a (a.id)}
							<label class="choice"><input type="radio" name="action" value={a.id} bind:group={form.action} /> <span style:--c={a.color}><i></i>{a.label}</span></label>
						{/each}
						<p class="hint">{actionOf(form.action).help}</p>
					</fieldset>
					{#if form.action !== 'remove'}
						<label for="se-name">Name <span class="hint">(optional; default: the town)</span></label>
						<input id="se-name" bind:value={form.name} maxlength="120" />
						<label for="se-class">Class <span class="hint">(optional; default: kept, or from the building count)</span></label>
						<select id="se-class" bind:value={form.settlement_class}>
							<option value="">From the building count</option>
							{#each CLASSES as c (c)}<option value={c}>{c}</option>{/each}
						</select>
					{/if}
					<label for="se-note">Note <span class="hint">(why, for the record)</span></label>
					<textarea id="se-note" bind:value={form.note} rows="2" maxlength="1000"></textarea>
					<div class="row">
						<button type="submit" class="primary" disabled={busy || (form.id === null && !form.geometry)}>{busy ? 'Applying…' : 'Save and apply'}</button>
						{#if form.id !== null}<button type="button" onclick={redraw}>{form.geometry ? 'Outline redrawn' : 'Redraw outline'}</button>{/if}
						<button type="button" onclick={() => ((form = null), stopDrawing())}>Cancel</button>
					</div>
				</form>
			{/if}

			<h2>Edits <span class="count">{edits.length}</span></h2>
			{#if !edits.length}
				<p class="hint">No edits yet. Pick an action above the map, then draw.</p>
			{:else}
				<ul class="list" aria-label="Settlement edits">
					{#each edits as e (e.id)}
						<li class:on={form?.id === e.id}>
							<button type="button" class="item" onclick={() => edit(e)}>
								<span class="badge" style:--c={actionOf(e.properties.action).color}>{actionOf(e.properties.action).label}</span>
								<strong>{e.properties.name ?? `#${e.id}`}</strong>
								{#if e.properties.settlement_class}<span class="hint">{e.properties.settlement_class}</span>{/if}
								{#if e.properties.note}<span class="note">{e.properties.note}</span>{/if}
							</button>
							<button type="button" class="del" aria-label="Delete edit #{e.id}" onclick={() => remove(e.id)}>✕</button>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	</div>
{/if}

<style>
	.crumb { margin: 0 0 0.3rem; font-size: 0.85rem; }
	.head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 0.5rem 1rem; margin-bottom: 0.8rem; }
	h1 { margin: 0; font-size: 1.4rem; }
	h2 { margin: 0.2rem 0 0.4rem; font-size: 1rem; display: flex; align-items: center; gap: 0.4rem; }
	.sub { margin: 0.2rem 0 0; color: var(--muted); font-size: 0.85rem; max-width: 80ch; }
	.stats { display: block; color: var(--text); font-weight: 600; margin-top: 0.2rem; }
	.editor { display: grid; grid-template-columns: 1fr minmax(300px, 380px); gap: 1rem; align-items: start; }
	.map-wrap { position: relative; height: 78vh; min-height: 520px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
	.map { position: absolute; inset: 0; }
	.toolbar { position: absolute; top: 10px; left: 10px; display: flex; flex-wrap: wrap; gap: 0.35rem; z-index: 2; }
	.toolbar button { font: inherit; font-size: 0.82rem; padding: 0.35rem 0.6rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; display: inline-flex; align-items: center; gap: 0.35rem; box-shadow: 0 2px 6px rgb(0 0 0 / 0.12); }
	.toolbar button.on { border-color: var(--c); box-shadow: inset 0 0 0 1.5px var(--c); }
	.toolbar i, .choice i, .badge::before { display: inline-block; width: 0.7rem; height: 0.7rem; border-radius: 2px; background: var(--c); }
	.badge::before { content: ''; margin-right: 0.3rem; vertical-align: -0.05rem; }
	.town { position: absolute; bottom: 30px; left: 10px; width: 220px; z-index: 2; }
	.town input { width: 100%; box-sizing: border-box; font: inherit; font-size: 0.85rem; padding: 0.35rem 0.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); }
	.town ul { list-style: none; margin: 0 0 0.25rem; padding: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; position: absolute; bottom: 100%; width: 100%; }
	.town ul button { all: unset; cursor: pointer; display: block; width: 100%; box-sizing: border-box; padding: 0.3rem 0.5rem; font-size: 0.85rem; }
	.town ul button:hover, .town ul button:focus-visible { background: var(--surface-muted); }
	.hint-pill { position: absolute; left: 50%; bottom: 18px; transform: translateX(-50%); margin: 0; z-index: 2; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 0.35rem 0.9rem; font-size: 0.82rem; box-shadow: 0 2px 8px rgb(0 0 0 / 0.12); white-space: nowrap; }
	.panel { display: grid; gap: 0.6rem; }
	.form { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.7rem 0.9rem; display: grid; gap: 0.35rem; }
	fieldset { border: none; padding: 0; margin: 0; display: grid; gap: 0.2rem; }
	legend { font-weight: 600; font-size: 0.85rem; margin-bottom: 0.15rem; }
	.choice { font-size: 0.85rem; display: flex; align-items: center; gap: 0.3rem; }
	.choice span { display: inline-flex; align-items: center; gap: 0.35rem; }
	label { font-size: 0.82rem; color: var(--muted); margin-top: 0.2rem; }
	input:not([type='radio']), select, textarea { font: inherit; font-size: 0.88rem; padding: 0.3rem 0.45rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg, #fff); color: inherit; }
	.row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.4rem; }
	.row button { font: inherit; font-size: 0.85rem; padding: 0.35rem 0.7rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }
	.row button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
	.row button:disabled { opacity: 0.55; cursor: not-allowed; }
	.count { font-size: 0.75rem; font-weight: 600; color: var(--muted); background: var(--surface-muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 0.45rem; }
	.list { list-style: none; margin: 0; padding: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; max-height: 50vh; overflow: auto; }
	.list li { display: flex; border-bottom: 1px solid var(--border); }
	.list li:last-child { border-bottom: none; }
	.list li.on { background: var(--surface-muted); }
	.item { all: unset; cursor: pointer; flex: 1; display: grid; gap: 0.1rem; padding: 0.45rem 0.7rem; font-size: 0.85rem; }
	.item:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
	.badge { font-size: 0.72rem; color: var(--muted); }
	.note { font-size: 0.78rem; color: var(--muted); }
	.del { all: unset; cursor: pointer; padding: 0 0.7rem; color: var(--muted); }
	.del:hover, .del:focus-visible { color: #b42318; }
	.hint { color: var(--muted); font-size: 0.78rem; margin: 0; }
	.error { color: #b42318; font-size: 0.85rem; margin: 0; }
	@media (max-width: 1000px) {
		.editor { grid-template-columns: 1fr; }
		.map-wrap { height: 60vh; }
	}
</style>
