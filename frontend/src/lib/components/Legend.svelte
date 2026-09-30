<script lang="ts">
	import type { LayerSpec } from '$lib/types';

	let { spec, color }: { spec: LayerSpec; color: string } = $props();

	// Swatch shape follows the first style fragment's type.
	const shape = $derived.by(() => {
		const t = spec.style?.layers?.[0]?.type;
		return t === 'line' ? 'line' : t === 'circle' ? 'circle' : t === 'raster' ? 'raster' : 'fill';
	});

	// Without an explicit legend, show one swatch in the layer's literal colour (if any).
	const autoColor = $derived.by(() => {
		const f = spec.style?.layers?.[0] as { paint?: Record<string, unknown> } | undefined;
		if (!f) return color;
		const c = f.paint?.['fill-color'] ?? f.paint?.['line-color'] ?? f.paint?.['circle-color'];
		return typeof c === 'string' ? c : null;
	});
</script>

{#if spec.legend?.type === 'categorical'}
	<div class="legend">
		{#if spec.legend.title}<div class="title">{spec.legend.title}</div>{/if}
		<ul>
			{#each spec.legend.items as item (item.label)}
				<li><span class="swatch {shape}" style:--c={item.color}></span>{item.label}</li>
			{/each}
		</ul>
	</div>
{:else if spec.legend?.type === 'gradient'}
	<div class="legend">
		{#if spec.legend.title}<div class="title">{spec.legend.title}</div>{/if}
		<div class="ramp" style:background="linear-gradient(to right, {spec.legend.stops.map((s) => s.color).join(', ')})"></div>
		<div class="ramp-labels">
			{#each spec.legend.stops as s (s.value)}<span>{s.value}</span>{/each}
		</div>
	</div>
{:else if spec.legend?.type === 'single'}
	<div class="legend"><ul><li><span class="swatch {shape}" style:--c={spec.legend.color}></span>{spec.legend.label ?? spec.title}</li></ul></div>
{:else if spec.legend?.type !== 'none' && autoColor && shape !== 'raster'}
	<div class="legend"><ul><li><span class="swatch {spec.style ? shape : 'fill'}" style:--c={autoColor}></span>{spec.title}</li></ul></div>
{/if}

<style>
	.legend { margin: 0.35rem 0 0.1rem; font-size: 0.78rem; color: var(--muted); }
	.title { font-weight: 600; margin-bottom: 0.2rem; color: var(--text); }
	ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.15rem; }
	li { display: flex; align-items: center; gap: 0.45rem; }
	.swatch { flex: none; display: inline-block; width: 14px; height: 14px; background: var(--c); }
	.swatch.fill { border-radius: 3px; border: 1px solid rgb(0 0 0 / 0.15); }
	.swatch.circle { border-radius: 50%; border: 1.5px solid #fff; box-shadow: 0 0 0 1px rgb(0 0 0 / 0.2); }
	.swatch.line { height: 3px; border-radius: 2px; }
	.ramp { height: 10px; border-radius: 3px; border: 1px solid rgb(0 0 0 / 0.1); }
	.ramp-labels { display: flex; justify-content: space-between; }
</style>
