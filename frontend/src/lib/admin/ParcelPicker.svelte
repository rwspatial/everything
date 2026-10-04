<script lang="ts">
	// Pick one tax parcel on a map (project builder, "Parcel site" design). The town comes first (chosen in the
	// builder): the map frames it, outlines it and draws only its parcels (pub.units__parcel vector tiles, filtered to
	// the town's GEOID by tiPG), from zoom 9, so a chosen town shows its parcels at once. Hover outlines a parcel, a click chooses it; the choice stays
	// highlighted, so another click changes it.
	import { onMount } from 'svelte';
	import { Map as MlMap, NavigationControl } from 'maplibre-gl';
	import '$lib/maplibre';
	import { resolveBasemap } from '$lib/basemaps';

	export interface PickedParcel {
		key: string;
		name: string;
		short_name: string;
		county_name: string | null;
		acres: number | null;
	}
	export interface PickerTown {
		key: string;
		name: string;
		bbox: [number, number, number, number];
	}

	let {
		tilesBase,
		town,
		selected = null,
		onpick
	}: { tilesBase: string; town: PickerTown | null; selected?: string | null; onpick: (p: PickedParcel) => void } = $props();

	const MINZOOM = 9; // tiles hold one town's parcels only, so even Portland is about 1 MB at zoom 9-11
	let container: HTMLDivElement;
	let map: MlMap | undefined;
	let zoom = $state(6.3);
	let ready = $state(false);

	const cql = (field: string, value: string) => encodeURIComponent(`${field}='${value.replace(/'/g, "''")}'`);
	const PARCEL_LAYERS = ['parcels-fill', 'parcels-line', 'parcels-hover', 'parcels-selected'];

	/** Replace the parcel and town-outline sources for the chosen town (or remove them when there is none). */
	function showTown(t: PickerTown | null) {
		if (!map) return;
		for (const id of [...PARCEL_LAYERS, 'town-outline-casing', 'town-outline']) if (map.getLayer(id)) map.removeLayer(id);
		for (const id of ['parcels', 'town']) if (map.getSource(id)) map.removeSource(id);
		if (!t) {
			map.flyTo({ center: [-69.2, 45.25], zoom: 6.3, duration: 600 });
			return;
		}
		map.addSource('town', {
			type: 'vector',
			tiles: [`${tilesBase}/collections/pub.units__town/tiles/WebMercatorQuad/{z}/{x}/{y}?properties=unit_key&filter=${cql('unit_key', t.key)}`],
			maxzoom: 14
		});
		map.addSource('parcels', {
			type: 'vector',
			tiles: [
				`${tilesBase}/collections/pub.units__parcel/tiles/WebMercatorQuad/{z}/{x}/{y}?properties=unit_key,name,short_name,county_name,acres&filter=${cql('town_geoid', t.key)}`
			],
			minzoom: MINZOOM,
			maxzoom: 16,
			attribution: 'Parcels: MEGIS'
		});
		const parcels = { source: 'parcels', 'source-layer': 'default', minzoom: MINZOOM };
		map.addLayer({ id: 'town-outline-casing', type: 'line', source: 'town', 'source-layer': 'default', paint: { 'line-color': '#ffffff', 'line-width': 5, 'line-opacity': 0.8 } });
		map.addLayer({ id: 'town-outline', type: 'line', source: 'town', 'source-layer': 'default', paint: { 'line-color': '#1d3557', 'line-width': 2 } });
		map.addLayer({ id: 'parcels-fill', type: 'fill', ...parcels, paint: { 'fill-color': '#b07d2b', 'fill-opacity': 0.08 } });
		map.addLayer({ id: 'parcels-line', type: 'line', ...parcels, paint: { 'line-color': '#8a5a16', 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.2, 15, 1] } });
		map.addLayer({ id: 'parcels-hover', type: 'line', ...parcels, filter: ['==', ['get', 'unit_key'], ''], paint: { 'line-color': '#1d3557', 'line-width': 2 } });
		map.addLayer({
			id: 'parcels-selected',
			type: 'fill',
			...parcels,
			filter: ['==', ['get', 'unit_key'], selected ?? ''],
			paint: { 'fill-color': '#2a78d6', 'fill-opacity': 0.4, 'fill-outline-color': '#1d3557' }
		});
		map.fitBounds(t.bbox, { padding: 24, duration: 700 });
	}

	$effect(() => {
		const t = town;
		if (ready) showTown(t);
	});
	$effect(() => {
		const key = selected ?? '';
		if (ready && map?.getLayer('parcels-selected')) map.setFilter('parcels-selected', ['==', ['get', 'unit_key'], key]);
	});

	onMount(() => {
		let disposed = false;
		const resizer = new ResizeObserver(() => map?.resize());
		resizer.observe(container);
		(async () => {
			const bm = await resolveBasemap('positron');
			if (disposed) return;
			map = new MlMap({ container, style: bm.style, center: [-69.2, 45.25], zoom: 6.3, attributionControl: { compact: true } });
			map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
			map.on('zoom', () => (zoom = map!.getZoom()));
			map.on('load', () => {
				map!.on('mousemove', 'parcels-fill', (e) => {
					map!.getCanvas().style.cursor = 'pointer';
					map!.setFilter('parcels-hover', ['==', ['get', 'unit_key'], String(e.features?.[0]?.properties?.unit_key ?? '')]);
				});
				map!.on('mouseleave', 'parcels-fill', () => {
					map!.getCanvas().style.cursor = '';
					if (map!.getLayer('parcels-hover')) map!.setFilter('parcels-hover', ['==', ['get', 'unit_key'], '']);
				});
				map!.on('click', 'parcels-fill', (e) => {
					const p = e.features?.[0]?.properties;
					if (!p) return;
					onpick({
						key: String(p.unit_key),
						name: String(p.name ?? ''),
						short_name: String(p.short_name ?? p.name ?? ''),
						county_name: p.county_name ? String(p.county_name) : null,
						acres: typeof p.acres === 'number' ? p.acres : null
					});
				});
				ready = true;
				// For tests: the picker's map.
				(window as unknown as { __parcelPicker?: MlMap }).__parcelPicker = map;
			});
		})();
		return () => {
			disposed = true;
			resizer.disconnect();
			map?.remove();
		};
	});
</script>

<div class="picker">
	<div class="map" bind:this={container} aria-label="Parcel map: click a parcel to choose it" role="application"></div>
	{#if !town}
		<p class="hint-pill" role="status">Choose a town first: its parcels appear here.</p>
	{:else if zoom < MINZOOM}
		<p class="hint-pill" role="status">Zoom in to see the parcels of {town.name}.</p>
	{/if}
</div>

<style>
	.picker { position: relative; height: 100%; }
	.map { position: absolute; inset: 0; }
	.hint-pill {
		position: absolute; left: 50%; bottom: 18px; transform: translateX(-50%); margin: 0; z-index: 2;
		background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 999px;
		padding: 0.35rem 0.9rem; font-size: 0.85rem; box-shadow: 0 2px 8px rgb(0 0 0 / 0.12); white-space: nowrap;
	}
</style>
