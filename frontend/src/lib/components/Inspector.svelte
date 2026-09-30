<script lang="ts">
	import { formatValue } from '$lib/format';
	import type { InspectedFeature } from '$lib/types';

	let { features, onclose }: { features: InspectedFeature[]; onclose: () => void } = $props();
	let closeButton: HTMLButtonElement | undefined = $state();

	$effect(() => {
		// Move focus into the drawer when it opens (keyboard and screen-reader users).
		if (features.length) closeButton?.focus({ preventScroll: true });
	});
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && onclose()} />

<aside class="inspector" aria-label="Feature details">
	<header>
		<h2>Feature details</h2>
		<button bind:this={closeButton} class="icon" onclick={onclose} aria-label="Close feature details">✕</button>
	</header>
	{#each features as f, i (i)}
		<section>
			<h3>{f.layerTitle}</h3>
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
		width: min(340px, 90vw);
		overflow: auto;
		background: var(--surface);
		border-left: 1px solid var(--border);
		padding: 0.75rem 1rem 1rem;
	}
	header { display: flex; align-items: center; justify-content: space-between; }
	h2 { font-size: 1rem; margin: 0; }
	h3 { font-size: 0.85rem; margin: 1rem 0 0.35rem; color: var(--accent-strong); }
	table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
	th, td { text-align: left; padding: 0.25rem 0.35rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	th { font-weight: 500; color: var(--muted); width: 40%; word-break: break-word; }
	td { word-break: break-word; }
	@media (max-width: 720px) {
		.inspector { position: absolute; right: 0; top: 0; bottom: 0; z-index: 5; box-shadow: -4px 0 16px rgb(0 0 0 / 0.15); }
	}
</style>
