<script lang="ts">
	// Small map of a dataset's coverage: received footprint (fill), requested extent (dashed),
	// missing areas (red) and parts coloured by status (current / stale / missing / failed).
	import { onMount } from 'svelte';
	import { Map as MlMap, NavigationControl } from 'maplibre-gl';
	import '$lib/maplibre';
	import { resolveBasemap } from '$lib/basemaps';
	import type { BBox } from './api';

	let { name, bbox }: { name: string; bbox: BBox | null } = $props();
	let container: HTMLDivElement;
	let featureCount = $state<number | null>(null);
	let error = $state<string | null>(null);

	onMount(() => {
		let map: MlMap | undefined;
		let disposed = false;
		// The card grid settles after the map is created; keep the canvas matched to its box.
		const resizer = new ResizeObserver(() => map?.resize());
		resizer.observe(container);
		(async () => {
			const [bm, res] = await Promise.all([
				resolveBasemap('positron'),
				fetch(`/api/admin/datasets/${encodeURIComponent(name)}/coverage.geojson`, { cache: 'no-store' })
			]);
			if (disposed) return;
			const data = res.ok ? await res.json() : { type: 'FeatureCollection', features: [] };
			if (!res.ok) error = `coverage request failed (${res.status})`;
			featureCount = data.features.length;
			map = new MlMap({
				container,
				style: bm.style,
				bounds: bbox ?? [-180, -60, 180, 75],
				fitBoundsOptions: { padding: 16 },
				attributionControl: { compact: true },
				cooperativeGestures: false
			});
			map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
			map.on('load', () => {
				map!.addSource('coverage', { type: 'geojson', data });
				const role = (r: string) => ['==', ['get', 'role'], r] as never;
				map!.addLayer({ id: 'received-fill', type: 'fill', source: 'coverage', filter: role('received'),
					paint: { 'fill-color': '#0b6e8a', 'fill-opacity': 0.35 } });
				map!.addLayer({ id: 'received-line', type: 'line', source: 'coverage', filter: role('received'),
					paint: { 'line-color': '#08566c', 'line-width': 0.8 } });
				map!.addLayer({ id: 'parts', type: 'fill', source: 'coverage', filter: role('part'),
					paint: {
						'fill-color': ['match', ['get', 'status'], 'current', '#1a9850', 'stale', '#e6a100',
							'missing', '#c0392b', 'failed', '#c0392b', 'loading', '#2b6cb0', '#8795a1'],
						'fill-opacity': 0.45
					} });
				map!.addLayer({ id: 'missing', type: 'fill', source: 'coverage', filter: role('missing'),
					paint: { 'fill-color': '#c0392b', 'fill-opacity': 0.4 } });
				map!.addLayer({ id: 'requested', type: 'line', source: 'coverage', filter: role('requested'),
					paint: { 'line-color': '#1d2733', 'line-width': 1.5, 'line-dasharray': [3, 2] } });
				window.__adminMap = { map: map!, ready: true, features: data.features.length };
			});
		})();
		return () => {
			disposed = true;
			resizer.disconnect();
			map?.remove();
			delete window.__adminMap;
		};
	});

</script>

<figure class="footprint">
	<div class="map" bind:this={container} role="region" aria-label="Coverage map for {name}"></div>
	<figcaption>
		<span class="key"><i class="sw received"></i>received footprint</span>
		<span class="key"><i class="sw requested"></i>requested extent</span>
		<span class="key"><i class="sw missing"></i>missing</span>
		{#if error}<span class="err">{error}</span>{:else if featureCount === 0}<span>no footprint recorded yet</span>{/if}
	</figcaption>
</figure>

<style>
	.footprint { margin: 0; }
	.map { height: 280px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
	figcaption { display: flex; flex-wrap: wrap; gap: 0.9rem; font-size: 0.75rem; color: var(--muted); margin-top: 0.35rem; }
	.key { display: inline-flex; align-items: center; gap: 0.3rem; }
	.sw { display: inline-block; width: 14px; height: 10px; border-radius: 2px; }
	.sw.received { background: rgb(11 110 138 / 0.45); border: 1px solid #08566c; }
	.sw.requested { border: 1.5px dashed #1d2733; }
	.sw.missing { background: rgb(192 57 43 / 0.5); }
	.err { color: #8a1c14; }
</style>
