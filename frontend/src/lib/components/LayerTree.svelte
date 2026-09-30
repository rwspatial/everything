<script lang="ts">
	import Legend from './Legend.svelte';
	import StatusBadge from './StatusBadge.svelte';
	import type { LayerState } from '$lib/types';

	interface Props {
		layers: LayerState[];
		ontoggle: (i: number) => void;
		onopacity: (i: number, value: number) => void;
		onmove: (i: number, direction: 1 | -1) => void;
		onparam: (i: number, param: string, value: number) => void;
	}
	let { layers, ontoggle, onopacity, onmove, onparam }: Props = $props();

	// Show topmost layer first, as map layer lists usually do. Keep the real index for callbacks.
	const rows = $derived(layers.map((ls, index) => ({ ls, index })).reverse());
	const groupStart = (k: number) => k === 0 || rows[k].ls.spec.group !== rows[k - 1].ls.spec.group;
	// A layer can move if there is a drawn (non-to-do) layer in that direction.
	const canMove = (i: number, d: 1 | -1) => {
		if (layers[i].spec.status === 'todo') return false;
		let j = i + d;
		while (j >= 0 && j < layers.length && layers[j].spec.status === 'todo') j += d;
		return j >= 0 && j < layers.length;
	};
</script>

<ul class="tree" aria-label="Layers, top to bottom">
	{#each rows as { ls, index }, k (ls.spec.id)}
		{#if ls.spec.group && groupStart(k)}
			<li class="group" aria-hidden="true">{ls.spec.group}</li>
		{/if}
		{@const todo = ls.spec.status === 'todo'}
		{@const cid = `layer-${ls.spec.id}`}
		<li class="layer" class:todo class:off={!ls.visible && !todo}>
			<div class="row">
				<input id={cid} type="checkbox" checked={ls.visible} disabled={todo} onchange={() => ontoggle(index)} />
				<label for={cid}>{ls.spec.title}</label>
				{#if todo}<StatusBadge status="todo" />{/if}
				{#if ls.error}<StatusBadge status="error" />{/if}
				<span class="move">
					<button class="icon" aria-label="Move {ls.spec.title} up" disabled={!canMove(index, 1)} onclick={() => onmove(index, 1)}>▲</button>
					<button class="icon" aria-label="Move {ls.spec.title} down" disabled={!canMove(index, -1)} onclick={() => onmove(index, -1)}>▼</button>
				</span>
			</div>
			{#if todo}
				<p class="note">{ls.spec.todo ?? 'Not configured yet.'}</p>
			{:else}
				{#if ls.error}<p class="error" role="alert">{ls.error}</p>{/if}
				<label class="slider">
					<span>Opacity</span>
					<input
						type="range"
						min="0"
						max="1"
						step="0.05"
						value={ls.opacity}
						aria-label="{ls.spec.title} opacity"
						oninput={(e) => onopacity(index, Number(e.currentTarget.value))}
					/>
					<output>{Math.round(ls.opacity * 100)}%</output>
				</label>
				{#each ls.spec.controls ?? [] as c (c.param)}
					<label class="slider">
						<span>{c.label}</span>
						<input
							type="range"
							min={c.min}
							max={c.max}
							step={c.step ?? 1}
							value={ls.params[c.param]}
							aria-label="{ls.spec.title}: {c.label}"
							onchange={(e) => onparam(index, c.param, Number(e.currentTarget.value))}
						/>
						<output>{ls.params[c.param]}</output>
					</label>
				{/each}
				<Legend spec={ls.spec} color={ls.color} />
			{/if}
		</li>
	{/each}
</ul>

<style>
	.tree { list-style: none; margin: 0; padding: 0; }
	.group {
		font-size: 0.7rem;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--muted);
		margin: 0.9rem 0 0.3rem;
	}
	.layer { padding: 0.55rem 0.6rem; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 0.45rem; background: var(--surface); }
	.layer.off { background: var(--surface-muted); }
	.layer.todo { background: var(--surface-muted); border-style: dashed; }
	.layer.todo label { color: var(--muted); }
	.row { display: flex; align-items: center; gap: 0.4rem; }
	.row label { flex: 1; font-weight: 600; font-size: 0.88rem; cursor: pointer; }
	.row input[type='checkbox'] { width: 1rem; height: 1rem; accent-color: var(--accent); }
	.move { display: inline-flex; gap: 0.1rem; }
	.move .icon { font-size: 0.65rem; padding: 0.15rem 0.3rem; }
	.note { margin: 0.35rem 0 0; font-size: 0.78rem; color: var(--muted); }
	.error { margin: 0.35rem 0 0; font-size: 0.78rem; color: #8a1c14; }
	.slider { display: grid; grid-template-columns: 5.5rem 1fr 2.8rem; align-items: center; gap: 0.4rem; font-size: 0.78rem; color: var(--muted); margin-top: 0.35rem; }
	.slider input { width: 100%; accent-color: var(--accent); }
	.slider output { text-align: right; font-variant-numeric: tabular-nums; color: var(--text); }
</style>
