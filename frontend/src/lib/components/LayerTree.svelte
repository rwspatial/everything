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

	// Opacity lives in one floating panel (a light-dismiss popover: Escape or a click elsewhere closes it), opened
	// from a small button on the layer row, so the list stays compact. The button shows the value when not 100 %.
	let panel = $state<HTMLDivElement>();
	let editing = $state<number | null>(null);
	let pos = $state({ top: 0, left: 0 });
	function openAdjust(i: number, e: MouseEvent) {
		const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const width = 240;
		pos = { top: r.bottom + 6, left: Math.max(8, Math.min(r.right - width, window.innerWidth - width - 8)) };
		editing = i;
		panel?.showPopover();
	}
	const pct = (v: number) => `${Math.round(v * 100)}%`;
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
				{#if !todo}
					<button
						class="icon adjust"
						class:changed={ls.opacity !== 1}
						aria-label="Adjust {ls.spec.title}"
						aria-haspopup="dialog"
						aria-expanded={editing === index}
						title="Opacity"
						onclick={(e) => openAdjust(index, e)}
						>{#if ls.opacity !== 1}{pct(ls.opacity)}{:else}<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"
								><path d="M2 4h7M13 4h1M2 12h1M7 12h7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /><circle
									cx="11"
									cy="4"
									r="1.8"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
								/><circle cx="5" cy="12" r="1.8" fill="none" stroke="currentColor" stroke-width="1.5" /></svg
							>{/if}</button
					>
				{/if}
				<span class="move">
					<button class="icon" aria-label="Move {ls.spec.title} up" disabled={!canMove(index, 1)} onclick={() => onmove(index, 1)}>▲</button>
					<button class="icon" aria-label="Move {ls.spec.title} down" disabled={!canMove(index, -1)} onclick={() => onmove(index, -1)}>▼</button>
				</span>
			</div>
			{#if todo}
				<p class="note">{ls.spec.todo ?? 'Not configured yet.'}</p>
			{:else}
				{#if ls.error}<p class="error" role="alert">{ls.error}</p>{/if}
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

<div
	class="adjust-panel"
	role="dialog"
	aria-label={editing !== null ? `Adjust ${layers[editing]?.spec.title}` : 'Adjust layer'}
	popover="auto"
	bind:this={panel}
	style:top="{pos.top}px"
	style:left="{pos.left}px"
	ontoggle={(e) => {
		if ((e as ToggleEvent).newState === 'closed') editing = null;
	}}
>
	{#if editing !== null && layers[editing]}
		{@const ls = layers[editing]}
		{@const i = editing}
		<div class="panel-head">
			<strong>{ls.spec.title}</strong>
			<button class="icon" aria-label="Close" onclick={() => panel?.hidePopover()}>✕</button>
		</div>
		<label class="slider">
			<span>Opacity</span>
			<input
				type="range"
				min="0"
				max="1"
				step="0.05"
				value={ls.opacity}
				aria-label="{ls.spec.title} opacity"
				oninput={(e) => onopacity(i, Number(e.currentTarget.value))}
			/>
			<output>{pct(ls.opacity)}</output>
		</label>
		{#if ls.opacity !== 1}<button class="reset" onclick={() => onopacity(i, 1)}>Reset to 100%</button>{/if}
	{/if}
</div>

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
	.adjust { font-size: 0.68rem; min-width: 1.6rem; padding: 0.15rem 0.3rem; display: inline-grid; place-items: center; color: var(--muted); }
	.adjust.changed { color: var(--accent-strong); font-weight: 700; font-variant-numeric: tabular-nums; }
	.adjust-panel {
		position: fixed; margin: 0; inset: auto; width: 240px; padding: 0.6rem 0.75rem 0.7rem;
		background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 10px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.16);
	}
	.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; font-size: 0.85rem; }
	.panel-head .icon { font-size: 0.7rem; padding: 0.1rem 0.35rem; }
	.adjust-panel .slider { grid-template-columns: 3.6rem 1fr 2.6rem; }
	.reset { margin-top: 0.45rem; font-size: 0.75rem; padding: 0.2rem 0.5rem; }
	.slider { display: grid; grid-template-columns: 5.5rem 1fr 2.8rem; align-items: center; gap: 0.4rem; font-size: 0.78rem; color: var(--muted); margin-top: 0.35rem; }
	.slider input { width: 100%; accent-color: var(--accent); }
	.slider output { text-align: right; font-variant-numeric: tabular-nums; color: var(--text); }
</style>
