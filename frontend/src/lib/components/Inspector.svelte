<script lang="ts">
	import { formatValue } from '$lib/format';
	import type { InspectedFeature } from '$lib/types';

	// A permanent panel beside the map (so a click never resizes the map), or a floating one over it (`overlay`, the
	// small embedded preview). Without a selection it says how to use it.
	let { features, onclose, overlay = false }: { features: InspectedFeature[]; onclose: () => void; overlay?: boolean } = $props();
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<aside class="inspector" class:overlay class:idle={!features.length} aria-label="Feature details" aria-live="polite">
	<header>
		<h2>Feature details</h2>
		{#if features.length}<button class="icon" onclick={onclose} aria-label="Clear feature details">✕</button>{/if}
	</header>
	{#if !features.length}
		<p class="hint">Click a feature on the map to see its attributes here. On a raster layer, the click reads the pixel value.</p>
	{/if}
	{#each features as f, i (i)}
		<section aria-labelledby="inspect-{i}">
			<h3 id="inspect-{i}">{f.layerTitle}</h3>
			<table>
				<tbody>
					{#each Object.entries(f.properties) as [key, value] (key)}
						<tr><th scope="row">{key}</th><td>{formatValue(value)}</td></tr>
					{/each}
				</tbody>
			</table>
		</section>
	{/each}
</aside>

<style>
	.inspector {
		grid-area: inspector;
		min-width: 0;
		overflow: auto;
		background: var(--surface);
		border-left: 1px solid var(--border);
		padding: 0.75rem 1rem 1rem;
	}
	header { display: flex; align-items: center; justify-content: space-between; min-height: 1.6rem; }
	.hint { font-size: 0.8rem; color: var(--muted); margin: 0.5rem 0 0; }
	/* Floating over the map (embedded preview): the map keeps its size. */
	.inspector.overlay { grid-area: auto; position: absolute; top: 3.4rem; right: 0.6rem; bottom: 2.6rem; width: min(300px, 80%); z-index: 5;
		border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 6px 24px rgb(0 0 0 / 0.16); }
	h2 { font-size: 1rem; margin: 0; }
	h3 { font-size: 0.85rem; margin: 1rem 0 0.35rem; color: var(--accent-strong); }
	table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
	th, td { text-align: left; padding: 0.25rem 0.35rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	th { font-weight: 500; color: var(--muted); width: 40%; word-break: break-word; }
	td { word-break: break-word; }
	@media (max-width: 720px) {
		.inspector { position: absolute; right: 0; top: 0; bottom: 0; width: min(320px, 88vw); z-index: 5; box-shadow: -4px 0 16px rgb(0 0 0 / 0.15); }
		.inspector.idle { display: none; }
	}
</style>
