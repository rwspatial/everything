<script lang="ts">
	// One chart (ChartSpec) drawn from its on-the-fly data (GET /api/projects/{slug}/charts/{id}).
	// D3 computes scales, arcs and ticks; Svelte renders the SVG. Every mark has a hover tooltip and reports a
	// MapLibre filter for the features behind it, so the viewer can highlight them on the map.
	import * as d3 from 'd3';
	import type { ChartSpec } from '$lib/contracts.gen';
	import { CATEGORICAL, OTHER, SERIES, fmt, fmtShort } from './format';

	interface BarRow { category: string; value: number | null; n: number; other?: boolean }
	interface Bin { x0: number; x1: number; count: number }
	interface Pt { id: number | string; x: number; y: number; label: string | null }
	interface Stat { label: string; value: number | null; format?: ChartSpec['format'] }
	export interface ChartData {
		type: ChartSpec['type'];
		rows?: BarRow[];
		bins?: Bin[];
		median?: number | null;
		open_end?: boolean;
		max?: number | null;
		points?: Pt[];
		r?: number | null;
		n?: number;
		stats?: Stat[];
	}

	let { spec, data, onhighlight }: { spec: ChartSpec; data: ChartData; onhighlight?: (filter: unknown[] | null) => void } = $props();

	const f = $derived(spec.format ?? 'number');
	let width = $state(320);
	let tip: { x: number; y: number; text: string } | null = $state(null);
	let showTable = $state(false);

	function hover(e: MouseEvent | FocusEvent, text: string, filter: unknown[] | null) {
		const box = (e.currentTarget as Element).closest('.chart')!.getBoundingClientRect();
		const p = 'clientX' in e ? { x: e.clientX, y: e.clientY } : (() => {
			const r = (e.currentTarget as Element).getBoundingClientRect();
			return { x: r.x + r.width / 2, y: r.y };
		})();
		tip = { x: p.x - box.x, y: p.y - box.y, text };
		onhighlight?.(filter);
	}
	function leave() {
		tip = null;
		onhighlight?.(null);
	}
	const eq = (field: string | undefined, v: string) => (field ? ['==', ['to-string', ['get', field]], v] : null);

	// ---- bar (horizontal, ranked) ----------------------------------------------------------------------------
	const BAR = 18;
	const barRows = $derived(data.rows ?? []);
	const labelW = $derived(Math.min(150, width * 0.38));
	const barX = $derived(d3.scaleLinear().domain([0, d3.max(barRows, (r) => r.value ?? 0) || 1]).range([0, Math.max(40, width - labelW - 64)]));
	// A bar with a 4px rounded data end and a square baseline.
	const barPath = (w: number, h: number) => {
		const r = Math.min(4, w / 2, h / 2);
		return `M0,0H${w - r}Q${w},0 ${w},${r}V${h - r}Q${w},${h} ${w - r},${h}H0Z`;
	};
	const trunc = (s: string, n = 22) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

	// ---- donut ---------------------------------------------------------------------------------------------------
	const R = 70;
	const pie = $derived(d3.pie<BarRow>().sort(null).value((r) => Math.max(0, r.value ?? 0)).padAngle(0.012)(barRows));
	const arc = d3.arc<d3.PieArcDatum<BarRow>>().innerRadius(R * 0.6).outerRadius(R).cornerRadius(2);
	const total = $derived(d3.sum(barRows, (r) => r.value ?? 0));
	const sliceColor = (r: BarRow, i: number) => (r.other ? OTHER : CATEGORICAL[i % CATEGORICAL.length]);

	// ---- histogram -------------------------------------------------------------------------------------------
	const H = 150;
	const M = { l: 44, r: 22, t: 10, b: 24 }; // right margin: room for the last axis label
	const bins = $derived(data.bins ?? []);
	const hx = $derived(d3.scaleLinear().domain([bins[0]?.x0 ?? 0, bins.at(-1)?.x1 ?? 1]).range([M.l, width - M.r]));
	const hy = $derived(d3.scaleLinear().domain([0, d3.max(bins, (b) => b.count) || 1]).nice(4).range([H - M.b, M.t]));
	const colPath = (x: number, y: number, w: number, h: number) => {
		const r = Math.min(4, w / 2, h);
		return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
	};
	const isLast = (b: Bin) => b === bins.at(-1);
	const binLabel = (b: Bin) => (data.open_end && isLast(b) ? `${fmt(b.x0, f)} and over` : `${fmt(b.x0, f)} – ${fmt(b.x1, f)}`);
	const binFilter = (b: Bin): unknown[] | null => {
		if (!spec.data.value) return null;
		const v = ['to-number', ['get', spec.data.value]];
		return data.open_end && isLast(b) ? ['>=', v, b.x0] : ['all', ['>=', v, b.x0], ['<=', v, b.x1]];
	};

	// ---- scatter ----------------------------------------------------------------------------------------------
	const SH = 200;
	const pts = $derived(data.points ?? []);
	const sx = $derived(d3.scaleLinear().domain(d3.extent(pts, (p) => p.x) as [number, number]).nice().range([M.l, width - M.r]));
	const sy = $derived(d3.scaleLinear().domain(d3.extent(pts, (p) => p.y) as [number, number]).nice().range([SH - M.b, M.t]));
	const yFmt = (v: number) => (spec.data.y?.includes('pct') ? `${v}%` : fmtShort(v));
</script>

<figure class="chart" bind:clientWidth={width} aria-label={spec.title}>
	<figcaption>
		<span class="title">{spec.title}</span>
		{#if spec.type !== 'stats'}
			<button type="button" class="table-toggle" aria-pressed={showTable} onclick={() => (showTable = !showTable)}>{showTable ? 'Chart' : 'Table'}</button>
		{/if}
	</figcaption>
	{#if spec.description}<p class="desc">{spec.description}</p>{/if}

	{#if spec.type === 'stats'}
		<div class="tiles">
			{#each data.stats ?? [] as s (s.label)}
				<div class="tile"><span class="big">{fmt(s.value, s.format ?? f)}</span><span class="lbl">{s.label}</span></div>
			{/each}
		</div>
	{:else if showTable}
		<table class="data">
			{#if spec.type === 'bar' || spec.type === 'donut'}
				<thead><tr><th>{spec.data.category}</th><th class="num">{spec.data.agg && spec.data.agg !== 'count' ? `${spec.data.agg} of ${spec.data.value}` : 'count'}</th></tr></thead>
				<tbody>{#each barRows as r (r.category)}<tr><td>{r.category}</td><td class="num">{fmt(r.value, f)}</td></tr>{/each}</tbody>
			{:else if spec.type === 'histogram'}
				<thead><tr><th>{spec.data.value}</th><th class="num">count</th></tr></thead>
				<tbody>{#each bins as b (b.x0)}<tr><td>{binLabel(b)}</td><td class="num">{fmt(b.count, 'count')}</td></tr>{/each}</tbody>
			{:else}
				<thead><tr><th>{spec.data.label ?? 'id'}</th><th class="num">{spec.data.x}</th><th class="num">{spec.data.y}</th></tr></thead>
				<tbody>{#each pts.slice(0, 200) as p (p.id)}<tr><td>{p.label ?? p.id}</td><td class="num">{fmt(p.x, f)}</td><td class="num">{fmt(p.y)}</td></tr>{/each}</tbody>
			{/if}
		</table>
	{:else if (spec.type === 'bar' || spec.type === 'donut' || spec.type === 'histogram' || spec.type === 'scatter') && !(barRows.length || bins.length || pts.length)}
		<p class="empty">No features {spec.scope === 'view' ? 'in view' : 'to chart'}.</p>
	{:else if spec.type === 'bar'}
		<svg width={width} height={barRows.length * (BAR + 8) + 4} role="img" aria-label="{spec.title}: bar chart">
			{#each barRows as r, i (r.category)}
				{@const w = Math.max(1, barX(r.value ?? 0))}
				<g transform="translate(0,{i * (BAR + 8) + 2})">
					<text class="cat" x={labelW - 6} y={BAR / 2} dy="0.35em" text-anchor="end">{trunc(r.category)}</text>
					<path
						d={barPath(w, BAR)}
						transform="translate({labelW},0)"
						fill={r.other ? OTHER : SERIES}
						role="button"
						tabindex="0"
						aria-label="{r.category}: {fmt(r.value, f)}"
						onmousemove={(e) => hover(e, `${r.category}: ${fmt(r.value, f)} (${fmt(r.n, 'count')} features)`, r.other ? null : eq(spec.data.category, r.category))}
						onfocus={(e) => hover(e, `${r.category}: ${fmt(r.value, f)}`, r.other ? null : eq(spec.data.category, r.category))}
						onmouseleave={leave}
						onblur={leave}
					/>
					<text class="val" x={labelW + w + 5} y={BAR / 2} dy="0.35em">{fmtShort(r.value ?? 0, f)}</text>
				</g>
			{/each}
		</svg>
	{:else if spec.type === 'donut'}
		<div class="donut">
			<svg width={R * 2 + 4} height={R * 2 + 4} role="img" aria-label="{spec.title}: donut chart">
				<g transform="translate({R + 2},{R + 2})">
					{#each pie as s, i (s.data.category)}
						<path
							d={arc(s)}
							fill={sliceColor(s.data, i)}
							stroke="#fff"
							stroke-width="1"
							role="button"
							tabindex="0"
							aria-label="{s.data.category}: {fmt(s.data.value, f)}"
							onmousemove={(e) => hover(e, `${s.data.category}: ${fmt(s.data.value, f)} (${total ? Math.round(((s.data.value ?? 0) / total) * 100) : 0}%)`, s.data.other ? null : eq(spec.data.category, s.data.category))}
							onfocus={(e) => hover(e, `${s.data.category}: ${fmt(s.data.value, f)}`, s.data.other ? null : eq(spec.data.category, s.data.category))}
							onmouseleave={leave}
							onblur={leave}
						/>
					{/each}
					<text class="center" text-anchor="middle" dy="-0.2em">{fmtShort(total, f)}</text>
					<text class="center-sub" text-anchor="middle" dy="1.1em">total</text>
				</g>
			</svg>
			<ul class="legend">
				{#each barRows as r, i (r.category)}
					<li><i style="background:{sliceColor(r, i)}"></i><span class="lc">{r.category}</span><span class="lv">{total ? Math.round(((r.value ?? 0) / total) * 100) : 0}%</span></li>
				{/each}
			</ul>
		</div>
	{:else if spec.type === 'histogram'}
		<svg width={width} height={H} role="img" aria-label="{spec.title}: histogram">
			{#each hy.ticks(4) as t (t)}
				<line class="grid" x1={M.l} x2={width - M.r} y1={hy(t)} y2={hy(t)} />
				<text class="tick" x={M.l - 6} y={hy(t)} dy="0.32em" text-anchor="end">{fmtShort(t, 'count')}</text>
			{/each}
			{#each bins as b (b.x0)}
				{@const x = hx(b.x0) + 1}
				{@const w = Math.max(1, hx(b.x1) - hx(b.x0) - 2)}
				{#if b.count}
					<path
						d={colPath(x, hy(b.count), w, hy(0) - hy(b.count))}
						fill={SERIES}
						role="button"
						tabindex="0"
						aria-label="{fmtShort(b.x0, f)} to {fmtShort(b.x1, f)}: {b.count}"
						onmousemove={(e) => hover(e, `${binLabel(b)}: ${fmt(b.count, 'count')}`, binFilter(b))}
						onfocus={(e) => hover(e, `${binLabel(b)}: ${fmt(b.count, 'count')}`, binFilter(b))}
						onmouseleave={leave}
						onblur={leave}
					/>
				{/if}
			{/each}
			<line class="axis" x1={M.l} x2={width - M.r} y1={hy(0)} y2={hy(0)} />
			{#each hx.ticks(4) as t (t)}
				<text class="tick" x={hx(t)} y={H - 6} text-anchor="middle">{fmtShort(t, f)}</text>
			{/each}
			{#if data.open_end}<text class="tick" x={width - M.r} y={M.t + 8} text-anchor="end">last bar: {fmtShort(bins.at(-1)?.x0 ?? 0, f)} and over (max {fmtShort(data.max ?? 0, f)})</text>{/if}
			{#if data.median !== null && data.median !== undefined}
				<line class="median" x1={hx(data.median)} x2={hx(data.median)} y1={M.t} y2={hy(0)} />
				<text class="tick strong" x={hx(data.median) + 4} y={M.t + 8}>median {fmtShort(data.median, f)}</text>
			{/if}
		</svg>
	{:else if spec.type === 'scatter'}
		<svg width={width} height={SH} role="img" aria-label="{spec.title}: scatter plot">
			{#each sy.ticks(4) as t (t)}
				<line class="grid" x1={M.l} x2={width - M.r} y1={sy(t)} y2={sy(t)} />
				<text class="tick" x={M.l - 6} y={sy(t)} dy="0.32em" text-anchor="end">{yFmt(t)}</text>
			{/each}
			{#each sx.ticks(4) as t (t)}
				<text class="tick" x={sx(t)} y={SH - 6} text-anchor="middle">{fmtShort(t, f)}</text>
			{/each}
			{#each pts as p (p.id)}
				<circle
					cx={sx(p.x)}
					cy={sy(p.y)}
					r="4"
					fill={SERIES}
					fill-opacity="0.7"
					stroke="#fff"
					stroke-width="1.5"
					role="button"
					tabindex="-1"
					aria-label={String(p.label ?? p.id)}
					onmousemove={(e) => hover(e, `${p.label ?? p.id}: ${fmt(p.x, f)}, ${fmt(p.y)}`, ['==', ['id'], p.id])}
					onmouseleave={leave}
				/>
			{/each}
		</svg>
		<p class="foot">{spec.data.x} (across) against {spec.data.y} (up); {fmt(data.n, 'count')} features{#if data.r !== null && data.r !== undefined}; correlation r = {data.r.toFixed(2)}{/if}</p>
	{/if}

	{#if tip}<div class="tip" class:flip={tip.x > width / 2} style="left:{tip.x}px; top:{tip.y - 34}px">{tip.text}</div>{/if}
</figure>

<style>
	.chart { position: relative; margin: 0; }
	figcaption { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; }
	.title { font-weight: 600; font-size: 0.88rem; color: var(--text); }
	.desc, .foot, .empty { font-size: 0.74rem; color: var(--muted); margin: 0.15rem 0 0.35rem; }
	.table-toggle { all: unset; cursor: pointer; font-size: 0.72rem; color: var(--accent-strong); text-decoration: underline; }
	.table-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
	svg { display: block; overflow: visible; }
	svg :global(path[role='button']), svg :global(circle[role='button']) { cursor: pointer; }
	svg :global(path[role='button']:hover), svg :global(path[role='button']:focus) { opacity: 0.8; outline: none; }
	.cat, .val, .tick { font-size: 11px; fill: var(--muted); }
	.cat { fill: var(--text); }
	.strong { fill: var(--text); font-weight: 600; }
	.center { font-size: 15px; font-weight: 700; fill: var(--text); }
	.center-sub { font-size: 10px; fill: var(--muted); }
	.grid { stroke: #e6e9ec; stroke-width: 1; }
	.axis { stroke: #9aa4ae; stroke-width: 1; }
	.median { stroke: var(--text); stroke-width: 1.5; stroke-dasharray: 3 3; }
	.donut { display: flex; gap: 0.8rem; align-items: center; }
	.legend { list-style: none; margin: 0; padding: 0; font-size: 0.76rem; display: grid; gap: 0.2rem; flex: 1; min-width: 0; }
	.legend li { display: grid; grid-template-columns: 10px 1fr auto; gap: 0.4rem; align-items: center; }
	.legend i { width: 10px; height: 10px; border-radius: 2px; }
	.lc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
	.lv { color: var(--muted); font-variant-numeric: tabular-nums; }
	.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(95px, 1fr)); gap: 0.5rem; margin-top: 0.3rem; }
	.tile { display: grid; gap: 0.1rem; padding: 0.45rem 0.55rem; background: var(--surface-muted); border-radius: 8px; }
	.big { font-size: 1.05rem; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
	.lbl { font-size: 0.72rem; color: var(--muted); }
	.data { width: 100%; border-collapse: collapse; font-size: 0.76rem; }
	.data th, .data td { text-align: left; padding: 0.2rem 0.3rem; border-bottom: 1px solid var(--border); }
	.data .num { text-align: right; font-variant-numeric: tabular-nums; }
	.tip.flip { transform: translateX(-100%); }
	.tip { position: absolute; pointer-events: none; background: #1d2733; color: #fff; font-size: 0.74rem; padding: 0.25rem 0.5rem; border-radius: 6px; white-space: nowrap; z-index: 5; }
</style>
