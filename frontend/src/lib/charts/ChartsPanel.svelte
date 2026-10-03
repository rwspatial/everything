<script lang="ts">
	// The viewer's Charts panel: the project's charts (manifest.charts), each fetched on the fly from core-api.
	// "In view" charts follow the map: they refetch (debounced) after every pan or zoom.
	import { untrack } from 'svelte';
	import type { ChartSpec } from '$lib/contracts.gen';
	import Chart, { type ChartData } from './Chart.svelte';

	let {
		slug,
		charts,
		bounds,
		moveTick,
		onhighlight,
		onclose
	}: {
		slug: string;
		charts: ChartSpec[];
		bounds: () => [number, number, number, number] | null;
		moveTick: number;
		onhighlight: (layerId: string | undefined, filter: unknown[] | null) => void;
		onclose: () => void;
	} = $props();

	interface State { scope: 'all' | 'view'; data: ChartData | null; error: string; loading: boolean }
	let states: Record<string, State> = $state(
		Object.fromEntries(untrack(() => charts).map((c) => [c.id, { scope: c.scope ?? 'all', data: null, error: '', loading: false }]))
	);

	async function load(c: ChartSpec) {
		const s = states[c.id];
		const b = s.scope === 'view' ? bounds() : null;
		const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
		const q = b ? `?bbox=${[clamp(b[0], -180, 180), clamp(b[1], -90, 90), clamp(b[2], -180, 180), clamp(b[3], -90, 90)].map((v) => v.toFixed(4)).join(',')}` : '';
		s.loading = true;
		try {
			const r = await fetch(`/api/projects/${slug}/charts/${c.id}${q}`);
			const body = await r.json();
			if (!r.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`);
			s.data = body;
			s.error = '';
		} catch (e) {
			s.error = (e as Error).message;
		} finally {
			s.loading = false;
		}
	}

	// First load of every chart.
	$effect(() => {
		for (const c of charts) void load(c);
	});
	// "In view" charts follow the map.
	$effect(() => {
		const tick = moveTick;
		if (!tick) return;
		const t = setTimeout(() => {
			for (const c of charts) if (states[c.id].scope === 'view') void load(c);
		}, 400);
		return () => clearTimeout(t);
	});

	function setScope(c: ChartSpec, scope: 'all' | 'view') {
		states[c.id].scope = scope;
		void load(c);
	}
</script>

<aside class="charts" aria-label="Charts">
	<header>
		<h2>Charts</h2>
		<button class="close" onclick={onclose} aria-label="Close charts">✕</button>
	</header>
	{#each charts as c (c.id)}
		{@const s = states[c.id]}
		<section class="card" aria-busy={s.loading}>
			{#if c.type !== 'stats' || c.scope === 'view'}
				<div class="scope" role="radiogroup" aria-label="Scope of {c.title}">
					<label><input type="radio" name="scope-{c.id}" checked={s.scope === 'all'} onchange={() => setScope(c, 'all')} /> Whole map</label>
					<label><input type="radio" name="scope-{c.id}" checked={s.scope === 'view'} onchange={() => setScope(c, 'view')} /> In view</label>
				</div>
			{/if}
			{#if s.error}
				<p class="error" role="alert">{c.title}: {s.error}</p>
			{:else if s.data}
				<Chart spec={{ ...c, scope: s.scope }} data={s.data} onhighlight={(f) => onhighlight(c.layer, f)} />
			{:else}
				<p class="loading">Loading {c.title}…</p>
			{/if}
		</section>
	{/each}
</aside>

<style>
	.charts { position: absolute; top: 0.6rem; right: 3.2rem; bottom: 0.6rem; width: min(380px, calc(100% - 4.4rem)); overflow: auto; z-index: 3;
		background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 6px 24px rgb(0 0 0 / 0.14); padding: 0.6rem 0.8rem 0.8rem; }
	header { display: flex; justify-content: space-between; align-items: center; position: sticky; top: -0.6rem; background: var(--surface); padding: 0.2rem 0; z-index: 1; }
	h2 { font-size: 0.95rem; margin: 0; }
	.close { all: unset; cursor: pointer; padding: 0.1rem 0.35rem; border-radius: 4px; }
	.close:focus-visible { outline: 2px solid var(--accent); }
	.card { border-top: 1px solid var(--border); padding: 0.6rem 0 0.4rem; }
	.card[aria-busy='true'] { opacity: 0.6; }
	.scope { display: flex; gap: 0.8rem; font-size: 0.72rem; color: var(--muted); margin-bottom: 0.25rem; }
	.scope label { display: inline-flex; gap: 0.25rem; align-items: center; }
	.loading { font-size: 0.78rem; color: var(--muted); }
	.error { font-size: 0.78rem; color: #b42318; }
</style>
