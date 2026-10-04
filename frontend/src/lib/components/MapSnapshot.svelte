<script lang="ts">
	// A still picture of a project's map for the printable report (/p/<slug>/report). The map is drawn once,
	// off-screen, with the viewer's adapters, opacity, route badges and icons, then replaced by an <img> so it
	// prints reliably (a live WebGL canvas does not). `onready` fires when the picture is in (or failed).
	import { onMount } from 'svelte';
	import { Map as MlMap } from 'maplibre-gl';
	import '$lib/maplibre';
	import { fragmentsFor, opacityPaint, toMapLibre, type AdapterContext } from '$lib/adapters';
	import { resolveBasemap } from '$lib/basemaps';
	import { loadIcons, providePoiIcon } from '$lib/icons';
	import { providePattern } from '$lib/patterns';
	import { addOverlays, hasOwnRoads, isRoadLayer, provideBadge } from '$lib/overlays';
	import { PALETTE } from '$lib/format';
	import type { ProjectManifest } from '$lib/types';

	let { manifest, tilesBase, height = 560, onready }: { manifest: ProjectManifest; tilesBase: string; height?: number; onready?: (error?: string) => void } =
		$props();

	let container = $state<HTMLDivElement>();
	let src = $state('');
	let failed = $state('');

	onMount(() => {
		let map: MlMap | undefined;
		let done = false;
		const finish = (error?: string) => {
			if (done) return;
			done = true;
			if (error) failed = error;
			onready?.(error);
		};
		const timer = setTimeout(() => finish('the map took too long to draw'), 90_000);
		(async () => {
			await loadIcons().catch(() => undefined);
			const bm = await resolveBasemap(manifest.view.basemap);
			map = new MlMap({
				container: container!,
				style: bm.style,
				center: manifest.view.center,
				zoom: manifest.view.zoom,
				interactive: false,
				attributionControl: false,
				fadeDuration: 0,
				canvasContextAttributes: { preserveDrawingBuffer: true }
			});
			if (manifest.view.bounds) map.fitBounds(manifest.view.bounds, { padding: 16, animate: false });
			map.setMissingStyleImageResolver(async (id) => {
				provideBadge(map!, id);
				providePoiIcon(map!, id);
				providePattern(map!, id);
			});
			map.on('style.load', () => addOverlays(map!, tilesBase, { roads: !hasOwnRoads(manifest) }));
			map.once('load', () => {
				const before = map!.getStyle().layers.find((l) => isRoadLayer(map!, l.id) || (l.type === 'symbol' && !l.id.startsWith('o:')))?.id;
				manifest.layers
					.filter((l) => l.status !== 'todo' && l.visible !== false)
					.forEach((spec, i) => {
						const ctx: AdapterContext = { tilesBase, color: PALETTE[i % PALETTE.length] };
						try {
							const parts = toMapLibre({ ...spec, visible: true }, ctx);
							if (!map!.getSource(parts.sourceId)) map!.addSource(parts.sourceId, parts.source);
							// Text labels need the basemap's fonts (none on the offline basemap).
							for (const layer of parts.layers)
								if (map!.getStyle().glyphs || !(layer as { layout?: Record<string, unknown> }).layout?.['text-field']) map!.addLayer(layer, before);
							if (spec.opacity !== undefined && spec.opacity !== 1) {
								fragmentsFor(spec, ctx).forEach((f, j) => {
									const id = parts.layers[j]?.id;
									if (!id) return;
									for (const [prop, value] of opacityPaint(f, spec.opacity!)) map!.setPaintProperty(id, prop as never, value as never);
								});
							}
						} catch {
							/* a layer that cannot be drawn is left out of the picture */
						}
					});
				map!.once('idle', () => {
					try {
						src = map!.getCanvas().toDataURL('image/png');
						finish();
					} catch (e) {
						finish(`could not capture the map: ${(e as Error).message}`);
					}
					clearTimeout(timer);
					map?.remove();
					map = undefined;
				});
			});
		})().catch((e) => finish((e as Error).message));
		return () => {
			clearTimeout(timer);
			map?.remove();
		};
	});
</script>

<div class="snapshot" style:height="{height}px">
	{#if src}
		<img {src} alt="Map: {manifest.title}" />
	{:else}
		<div class="live" bind:this={container}></div>
		{#if failed}<p class="failed">{failed}</p>{/if}
	{/if}
</div>

<style>
	.snapshot { position: relative; width: 100%; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; background: #eef1f4; }
	.live { position: absolute; inset: 0; }
	img { display: block; width: 100%; height: 100%; object-fit: contain; }
	.failed { position: absolute; inset: auto 0 0 0; margin: 0; padding: 0.4rem 0.6rem; background: #fde3e1; color: #8a1c14; font-size: 0.8rem; }
</style>
