<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { Map as MlMap, NavigationControl, Popup, ScaleControl } from 'maplibre-gl';
	import type { GeoJSONSource, MapGeoJSONFeature, PointLike, StyleSpecification, VectorTileSource } from 'maplibre-gl';
	import '$lib/maplibre';
	import { fragmentsFor, isProjectId, opacityPaint, sourceIdFor, toMapLibre } from '$lib/adapters';
	import type { AdapterContext } from '$lib/adapters';
	import { basemaps, DEFAULT_BASEMAP, resolveBasemap } from '$lib/basemaps';
	import type { AppConfig } from '$lib/config';
	import { fillTemplate, formatValue, PALETTE } from '$lib/format';
	import type { InspectedFeature, LayerState, ProjectManifest, SourceSpec } from '$lib/types';
	import Inspector from './Inspector.svelte';
	import LayerTree from './LayerTree.svelte';
	import StatusBadge from './StatusBadge.svelte';

	let {
		manifest,
		config,
		embedded = false
	}: {
		manifest: ProjectManifest;
		config: AppConfig;
		/** Preview inside another page (the /admin/new wizard): fill the parent, leave the page URL alone. */
		embedded?: boolean;
	} = $props();

	// ---- initial state: manifest defaults, overridden by the URL (shareable views) ----------
	// Read once: the viewer is re-created (keyed) when its inputs change.
	const q = untrack(() => embedded) ? new URLSearchParams() : new URL(window.location.href).searchParams;

	function initialLayers(): LayerState[] {
		let states: LayerState[] = manifest.layers.map((spec, i) => ({
			spec,
			visible: spec.status !== 'todo' && spec.visible !== false,
			opacity: spec.opacity ?? 1,
			params: { ...(('params' in spec.source && spec.source.params) || {}) },
			error: null,
			color: PALETTE[i % PALETTE.length]
		}));
		const v = q.get('v');
		if (v !== null) {
			const on = new Set(v.split(',').filter(Boolean));
			for (const s of states) s.visible = s.spec.status !== 'todo' && on.has(s.spec.id);
		}
		const o = q.get('o');
		if (o) {
			const rank = new Map(o.split(',').map((id, i) => [id, i]));
			states = [...states].sort((a, b) => (rank.get(b.spec.id) ?? 1e9) - (rank.get(a.spec.id) ?? 1e9));
		}
		for (const pair of (q.get('op') ?? '').split(',').filter(Boolean)) {
			const [id, val] = pair.split(':');
			const s = states.find((x) => x.spec.id === id);
			if (s && !Number.isNaN(Number(val))) s.opacity = Math.min(1, Math.max(0, Number(val)));
		}
		for (const [key, val] of q) {
			const m = key.match(/^pa\.([^.]+)\.(.+)$/);
			const s = m && states.find((x) => x.spec.id === m[1]);
			if (s && m) s.params[m[2]] = Number.isNaN(Number(val)) ? val : Number(val);
		}
		return states;
	}

	function initialView(): { center: [number, number]; zoom: number } | null {
		const parts = (q.get('map') ?? '').split('/').map(Number);
		if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
		return { zoom: parts[0], center: [parts[2], parts[1]] };
	}

	let layers = $state<LayerState[]>(initialLayers());
	let selected = $state<InspectedFeature[]>([]);
	let cursor = $state<[number, number] | null>(null);
	// The viewer is re-created per project ({#key slug}), so reading the initial manifest is intended.
	// svelte-ignore state_referenced_locally
	let zoom = $state(manifest.view.zoom);
	let busy = $state(true);
	// svelte-ignore state_referenced_locally
	let basemapKey = $state(q.get('b') ?? manifest.view.basemap ?? DEFAULT_BASEMAP);
	let basemapFallback = $state(false);
	let panelOpen = $state(typeof window !== 'undefined' ? window.innerWidth > 720 : true);
	let copied = $state(false);
	let container: HTMLDivElement;
	let map: MlMap | undefined;

	const errorCount = $derived(layers.filter((l) => l.error).length);
	const ctxFor = (ls: LayerState): AdapterContext => ({ tilesBase: config.tilesBase, params: ls.params, color: ls.color });
	const idsFor = (ls: LayerState) => fragmentsFor(ls.spec, ctxFor(ls)).map((_, i) => `${sourceIdFor(ls.spec.id)}:${i}`);
	const active = () => layers.filter((l) => l.spec.status !== 'todo');

	// ---- map lifecycle ----------------------------------------------------------------------
	/** Basemap label layers (vector symbols, or raster overlays tagged via LABELS_METADATA). */
	const isLabelLayer = (l: { id: string; type: string; metadata?: unknown }) =>
		!isProjectId(l.id) && (l.type === 'symbol' || (l.metadata as Record<string, unknown> | undefined)?.['spatial:labels'] === true);
	/** First basemap label layer: project layers go below it so place names stay readable. */
	const labelAnchor = () => map?.getStyle().layers.find(isLabelLayer)?.id;

	function addProjectLayers() {
		if (!map) return;
		const before = labelAnchor();
		for (const ls of active()) {
			try {
				const parts = toMapLibre({ ...ls.spec, visible: ls.visible }, ctxFor(ls));
				if (!map.getSource(parts.sourceId)) map.addSource(parts.sourceId, parts.source);
				for (const layer of parts.layers) if (!map.getLayer(layer.id)) map.addLayer(layer, before);
				if (ls.opacity !== 1) applyOpacity(ls);
			} catch (e) {
				ls.error = `Could not add layer: ${(e as Error).message}`;
			}
		}
	}

	function applyOpacity(ls: LayerState) {
		if (!map) return;
		const ids = idsFor(ls);
		fragmentsFor(ls.spec, ctxFor(ls)).forEach((f, i) => {
			if (!map!.getLayer(ids[i])) return;
			for (const [prop, value] of opacityPaint(f, ls.opacity)) map!.setPaintProperty(ids[i], prop as never, value as never);
		});
	}

	function restack() {
		if (!map) return;
		const before = labelAnchor();
		for (const ls of active()) for (const id of idsFor(ls)) if (map.getLayer(id)) map.moveLayer(id, before);
	}

	// Test/automation hook: lets e2e tests assert that features are actually drawn.
	const hook = {
		ready: false,
		idle: false,
		get map() {
			return map;
		},
		renderedCount(layerId: string): number {
			const ls = layers.find((l) => l.spec.id === layerId);
			if (!map || !ls) return 0;
			const ids = idsFor(ls).filter((id) => map!.getLayer(id));
			return ids.length ? map.queryRenderedFeatures({ layers: ids }).length : 0;
		}
	};

	onMount(() => {
		let disposed = false;
		(async () => {
			const bm = await resolveBasemap(basemapKey);
			if (disposed) return;
			basemapKey = bm.key;
			basemapFallback = bm.fallback;
			const view = initialView();
			map = new MlMap({
				container,
				style: bm.style,
				center: view?.center ?? manifest.view.center,
				zoom: view?.zoom ?? manifest.view.zoom,
				attributionControl: { compact: true }
			});
			map.addControl(new NavigationControl({ visualizePitch: false }), 'top-right');
			map.addControl(new ScaleControl({}), 'bottom-right');
			if (!view && manifest.view.bounds) map.fitBounds(manifest.view.bounds, { padding: 24, animate: false });

			const hover = new Popup({ closeButton: false, closeOnClick: false, maxWidth: '280px', className: 'hover-popup' });
			map.on('load', () => {
				addProjectLayers();
				hook.ready = true;
				window.__spatial = hook;
			});
			map.on('dataloading', () => {
				busy = true;
				hook.idle = false;
			});
			map.on('idle', () => {
				busy = false;
				hook.idle = hook.ready;
			});
			map.on('moveend', () => {
				zoom = map!.getZoom();
				syncUrl();
			});
			map.on('mousemove', (e) => {
				cursor = [e.lngLat.lng, e.lngLat.lat];
				const hit = featuresAt(e.point)[0];
				map!.getCanvas().style.cursor = hit ? 'pointer' : '';
				const template = hit?.ls.spec.interaction?.popup?.template;
				if (hit && template) hover.setLngLat(e.lngLat).setText(fillTemplate(template, hit.feature.properties)).addTo(map!);
				else hover.remove();
			});
			map.on('mouseout', () => {
				cursor = null;
				hover.remove();
			});
			map.on('click', async (e) => {
				const vectors = featuresAt(e.point)
					.filter((h) => h.ls.spec.interaction?.inspect !== false)
					.slice(0, 10)
					.map((h) => ({ layerId: h.ls.spec.id, layerTitle: h.ls.spec.title, properties: { ...h.feature.properties } }));
				selected = vectors;
				const click = ++clickSeq; // $state wraps arrays in proxies, so compare clicks, not arrays
				const pixels = await rasterValuesAt(e.lngLat.lng, e.lngLat.lat);
				if (pixels.length && click === clickSeq) selected = [...pixels, ...vectors];
			});
			map.on('error', (e) => {
				const sourceId = (e as unknown as { sourceId?: string }).sourceId;
				const ls = sourceId && isProjectId(sourceId) ? layers.find((l) => sourceIdFor(l.spec.id) === sourceId) : undefined;
				if (ls) ls.error ??= `Data failed to load: ${e.error?.message ?? 'unknown error'}`;
				else console.warn('map error', e.error);
			});
		})();
		return () => {
			disposed = true;
			map?.remove();
			delete window.__spatial;
		};
	});

	let clickSeq = 0;

	/** Pixel values under the click for visible COG layers (titiler point query through the proxy). */
	async function rasterValuesAt(lng: number, lat: number): Promise<InspectedFeature[]> {
		const cogs = active().filter((l) => l.visible && l.spec.source.type === 'raster-cog' && l.spec.interaction?.inspect !== false);
		const found = await Promise.all(
			cogs.map(async (l): Promise<InspectedFeature | null> => {
				const src = l.spec.source as Extract<SourceSpec, { type: 'raster-cog' }>;
				try {
					const r = await fetch(`/raster/${src.cog}/point/${lng.toFixed(5)},${lat.toFixed(5)}`);
					if (!r.ok) return null; // outside the raster, or nodata
					const v = (await r.json()).values?.[src.bidx ? src.bidx - 1 : 0];
					if (typeof v !== 'number' || !Number.isFinite(v)) return null;
					const category = src.categories?.find((c) => c.value === v);
					const value = category
						? (category.label ?? String(v))
						: `${Math.round(v * 10) / 10}${src.units ? ` ${src.units}` : ''}`;
					return { layerId: l.spec.id, layerTitle: l.spec.title, properties: { value } };
				} catch {
					return null;
				}
			})
		);
		return found.filter((f): f is InspectedFeature => f !== null);
	}

	function featuresAt(p: { x: number; y: number }): { ls: LayerState; feature: MapGeoJSONFeature }[] {
		if (!map) return [];
		const ids = active()
			.filter((l) => l.visible)
			.flatMap(idsFor)
			.filter((id) => map!.getLayer(id));
		if (!ids.length) return [];
		const box: [PointLike, PointLike] = [
			[p.x - 4, p.y - 4],
			[p.x + 4, p.y + 4]
		];
		return map
			.queryRenderedFeatures(box, { layers: ids })
			.map((feature) => ({ feature, ls: layers.find((l) => sourceIdFor(l.spec.id) === feature.source)! }))
			.filter((h) => h.ls);
	}

	// ---- layer controls ---------------------------------------------------------------------
	function toggle(i: number) {
		const ls = layers[i];
		ls.visible = !ls.visible;
		for (const id of idsFor(ls)) if (map?.getLayer(id)) map.setLayoutProperty(id, 'visibility', ls.visible ? 'visible' : 'none');
		syncUrl();
	}

	function setOpacity(i: number, value: number) {
		layers[i].opacity = value;
		applyOpacity(layers[i]);
		syncUrl();
	}

	function move(i: number, direction: 1 | -1) {
		// Skip over to-do layers: they are not drawn, so swapping with them changes nothing visible.
		let j = i + direction;
		while (j >= 0 && j < layers.length && layers[j].spec.status === 'todo') j += direction;
		if (j < 0 || j >= layers.length) return;
		[layers[i], layers[j]] = [layers[j], layers[i]];
		restack();
		syncUrl();
	}

	function setParam(i: number, param: string, value: number) {
		const ls = layers[i];
		ls.params[param] = value;
		ls.error = null;
		const parts = toMapLibre(ls.spec, ctxFor(ls));
		const src = map?.getSource(parts.sourceId);
		if (src && parts.source.type === 'vector') (src as VectorTileSource).setTiles(parts.source.tiles ?? []);
		else if (src && parts.source.type === 'geojson') (src as GeoJSONSource).setData(parts.source.data as string);
		syncUrl();
	}

	async function switchBasemap(key: string) {
		if (!map) return;
		const bm = await resolveBasemap(key);
		basemapKey = bm.key;
		basemapFallback = bm.fallback;
		map.setStyle(bm.style, {
			// Carry the project's sources and layers (current paint/visibility) onto the new basemap.
			transformStyle: (prev, next) => {
				const ours = (prev?.layers ?? []).filter((l) => isProjectId(l.id));
				const cut = next.layers.findIndex(isLabelLayer);
				const at = cut === -1 ? next.layers.length : cut;
				return {
					...next,
					sources: { ...next.sources, ...Object.fromEntries(Object.entries(prev?.sources ?? {}).filter(([id]) => isProjectId(id))) },
					layers: [...next.layers.slice(0, at), ...ours, ...next.layers.slice(at)]
				} as StyleSpecification;
			}
		});
		syncUrl();
	}

	function resetView() {
		if (!map) return;
		if (manifest.view.bounds) map.fitBounds(manifest.view.bounds, { padding: 24 });
		else map.flyTo({ center: manifest.view.center, zoom: manifest.view.zoom });
	}

	async function copyLink() {
		try {
			await navigator.clipboard.writeText(window.location.href);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		} catch {
			window.prompt('Copy this link:', window.location.href);
		}
	}

	// ---- URL state (debounced) ----------------------------------------------------------------
	let urlTimer: ReturnType<typeof setTimeout> | undefined;
	function syncUrl() {
		clearTimeout(urlTimer);
		urlTimer = setTimeout(() => {
			if (!map || embedded) return;
			const p = new URLSearchParams();
			const c = map.getCenter();
			p.set('map', `${map.getZoom().toFixed(2)}/${c.lat.toFixed(4)}/${c.lng.toFixed(4)}`);
			p.set('v', layers.filter((l) => l.visible).map((l) => l.spec.id).join(','));
			const order = layers.map((l) => l.spec.id);
			if (order.join(',') !== manifest.layers.map((l) => l.id).join(',')) p.set('o', [...order].reverse().join(','));
			const ops = layers.filter((l) => l.opacity !== 1).map((l) => `${l.spec.id}:${l.opacity}`);
			if (ops.length) p.set('op', ops.join(','));
			for (const l of layers) {
				const defaults = ('params' in l.spec.source && l.spec.source.params) || {};
				for (const [k, v] of Object.entries(l.params)) if (String(v) !== String(defaults[k])) p.set(`pa.${l.spec.id}.${k}`, String(v));
			}
			if (basemapKey !== (manifest.view.basemap ?? DEFAULT_BASEMAP)) p.set('b', basemapKey);
			try {
				replaceState(`?${p.toString().replace(/%2C/g, ',').replace(/%2F/g, '/').replace(/%3A/g, ':')}`, {});
			} catch {
				/* router not ready yet; the next change will sync */
			}
		}, 250);
	}
</script>

<div class="viewer" class:panel-closed={!panelOpen} class:embedded>
	<header class="topbar">
		{#if !embedded}<a class="back" href="/maps">← All maps</a>{/if}
		<h1>{manifest.title}</h1>
		<StatusBadge status={manifest.status} />
		<span class="spacer"></span>
		<label class="basemap" for="basemap-select">
			<span class="basemap-label">Basemap</span>
			<select id="basemap-select" aria-label="Basemap" value={basemapKey} onchange={(e) => switchBasemap(e.currentTarget.value)}>
				{#each Object.entries(basemaps) as [key, b] (key)}<option value={key}>{b.label}</option>{/each}
			</select>
		</label>
		<button onclick={resetView}>Reset view</button>
		{#if !embedded}<button onclick={copyLink} aria-live="polite">{copied ? 'Link copied' : 'Copy link'}</button>{/if}
		<button class="panel-toggle" aria-expanded={panelOpen} aria-controls="layer-panel" onclick={() => (panelOpen = !panelOpen)}>
			Layers
		</button>
	</header>

	<aside id="layer-panel" class="panel" aria-label="Layer controls" hidden={!panelOpen}>
		{#if manifest.description}<p class="description">{manifest.description}</p>{/if}
		{#if manifest.notes?.length}
			<section class="notes" aria-label="Project to-do notes">
				<h2>Still to do</h2>
				<ul>{#each manifest.notes as n (n)}<li>{n}</li>{/each}</ul>
			</section>
		{/if}
		{#if layers.length}
			<LayerTree {layers} ontoggle={toggle} onopacity={setOpacity} onmove={move} onparam={setParam} />
		{:else}
			<p class="empty">This project has no layers yet.</p>
		{/if}
	</aside>

	<main class="map-wrap">
		<div class="map" bind:this={container} role="region" aria-label="Map: {manifest.title}"></div>
		{#if basemapFallback}
			<p class="notice" role="status">Basemap unreachable (offline?). Showing a plain background; project data is unaffected.</p>
		{/if}
	</main>

	{#if selected.length}
		<Inspector features={selected} onclose={() => (selected = [])} />
	{/if}

	<footer class="statusbar">
		<span>{cursor ? `${formatValue(cursor[1])}°, ${formatValue(cursor[0])}°` : 'Move over the map'}</span>
		<span>Zoom {zoom.toFixed(1)}</span>
		<span role="status">{busy ? 'Loading…' : 'Ready'}</span>
		{#if errorCount}<span class="err" role="alert">{errorCount} layer{errorCount > 1 ? 's' : ''} failed, see the layer list</span>{/if}
	</footer>
</div>

<style>
	.viewer {
		height: 100dvh;
		display: grid;
		grid-template-rows: auto 1fr auto;
		grid-template-columns: 330px 1fr auto;
		grid-template-areas: 'top top top' 'panel map inspector' 'status status status';
	}
	.viewer.panel-closed { grid-template-columns: 0 1fr auto; }
	.viewer.embedded { height: 100%; }
	.topbar {
		grid-area: top;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.9rem;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
		flex-wrap: wrap;
	}
	.topbar h1 { font-size: 1.05rem; margin: 0; }
	.back { font-size: 0.85rem; }
	.spacer { flex: 1; }
	.basemap { display: flex; align-items: center; gap: 0.4rem; font-size: 0.82rem; color: var(--muted); }
	.panel { grid-area: panel; overflow: auto; padding: 0.8rem; background: var(--surface-muted); border-right: 1px solid var(--border); }
	.panel[hidden] { display: none; }
	.description { font-size: 0.85rem; color: var(--muted); margin: 0 0 0.6rem; }
	.notes { background: #fff8e1; border: 1px solid #f0d68a; border-radius: 8px; padding: 0.5rem 0.75rem; margin-bottom: 0.6rem; font-size: 0.8rem; }
	.notes h2 { font-size: 0.8rem; margin: 0 0 0.25rem; color: #6b4700; }
	.notes ul { margin: 0; padding-left: 1.1rem; }
	.empty { color: var(--muted); font-size: 0.85rem; }
	.map-wrap { grid-area: map; position: relative; min-height: 0; }
	.map { position: absolute; inset: 0; }
	.notice {
		position: absolute;
		left: 50%;
		top: 0.75rem;
		transform: translateX(-50%);
		margin: 0;
		padding: 0.4rem 0.75rem;
		background: #fff8e1;
		border: 1px solid #f0d68a;
		border-radius: 6px;
		font-size: 0.8rem;
	}
	.statusbar {
		grid-area: status;
		display: flex;
		gap: 1.25rem;
		padding: 0.3rem 0.9rem;
		font-size: 0.78rem;
		color: var(--muted);
		background: var(--surface);
		border-top: 1px solid var(--border);
		font-variant-numeric: tabular-nums;
	}
	.statusbar .err { color: #8a1c14; font-weight: 600; }
	:global(.hover-popup .maplibregl-popup-content) { font-size: 0.8rem; padding: 0.35rem 0.6rem; }
	@media (max-width: 720px) {
		.viewer, .viewer.panel-closed { grid-template-columns: 1fr; grid-template-areas: 'top' 'map' 'status'; }
		.panel { position: absolute; z-index: 4; top: 3.2rem; bottom: 1.8rem; left: 0; width: min(330px, 88vw); box-shadow: 4px 0 16px rgb(0 0 0 / 0.15); }
		.basemap-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
	}
</style>
