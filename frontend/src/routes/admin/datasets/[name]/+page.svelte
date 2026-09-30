<script lang="ts">
	import Badge from '$lib/admin/Badge.svelte';
	import FootprintMap from '$lib/admin/FootprintMap.svelte';
	import { fmtAgo, fmtBBox, fmtBytes, fmtDate, fmtDuration, fmtNum } from '$lib/admin/api';

	let { data } = $props();
	const d = $derived(data.d);
	const table = $derived(d.outputs.find((o) => o.kind === 'postgis_table'));
	const latestCheck = $derived(d.freshness_checks[0]);
	const single = $derived(d.parts.length === 1 && d.parts[0].part_key === '*' ? d.parts[0] : null);
	let copied = $state(false);

	async function copyAttribution() {
		if (!d.attribution) return;
		await navigator.clipboard.writeText(d.attribution);
		copied = true;
		setTimeout(() => (copied = false), 1500);
	}

	const kindLabel: Record<string, string> = {
		postgis_table: 'PostGIS table',
		pub_view: 'Published view / function',
		materialized_view: 'Materialized view',
		tipg_collection: 'tiPG collection',
		cog: 'Cloud Optimized GeoTIFF',
		tile_url: 'Tile URL'
	};
	const cli = $derived(`make import-recipe r=${d.name}${d.enabled ? '' : ' force=1'}`);
</script>

<svelte:head><title>{d.title} · Admin</title></svelte:head>

<p class="crumbs"><a href="/admin">← Datasets</a></p>

<header class="head">
	<div>
		<h1>{d.title}</h1>
		<p class="sub"><code>{d.name}</code> · {d.kind}{d.group_name ? ` · ${d.group_name}` : ''}{d.agency ? ` · ${d.agency}` : ''}</p>
	</div>
	<div class="badges">
		<Badge value={d.status} title="overall status" />
		<Badge value={d.freshness ?? 'unknown'} title="freshness" />
		{#if !d.enabled}<Badge value="disabled" />{/if}
	</div>
</header>
{#if d.description}<p class="desc">{d.description}</p>{/if}
{#if d.todo}<p class="todo"><strong>To do:</strong> {d.todo}</p>{/if}

<div class="grid">
	<section class="card" aria-labelledby="cov-h">
		<h2 id="cov-h">Coverage</h2>
		<FootprintMap name={d.name} bbox={d.bbox} />
		<dl class="facts">
			<dt>Extent</dt><dd>{d.extent_name ?? d.coverage?.extent ?? '–'}</dd>
			<dt>Bounding box</dt><dd>{fmtBBox(d.bbox)}</dd>
			<dt>Received vs requested</dt>
			<dd>{d.received_ratio === null ? 'n/a (no requested extent declared)' : `${Math.round(d.received_ratio * 100)} %`}</dd>
		</dl>
	</section>

	<section class="card" aria-labelledby="id-h">
		<h2 id="id-h">Identity &amp; data</h2>
		<dl class="facts">
			<dt>Source</dt>
			<dd>
				{#if d.upstream?.url}<a href={d.upstream.url} rel="external noopener">{d.upstream.url}</a>
				{:else if d.upstream?.path}<code>data/incoming/{d.upstream.path}</code>{:else}–{/if}
			</dd>
			<dt>License</dt><dd>{d.license ?? '–'}</dd>
			<dt>Attribution</dt>
			<dd>
				{d.attribution ?? '–'}
				{#if d.attribution}<button class="small" onclick={copyAttribution}>{copied ? 'Copied' : 'Copy'}</button>{/if}
			</dd>
			<dt>Vintage</dt><dd>{d.vintage?.label ?? '–'}</dd>
			<dt>Stored CRS</dt><dd>{table?.srid ? `EPSG:${table.srid}` : '–'}{table?.source_srs ? ` (source ${table.source_srs})` : ''}</dd>
			<dt>Geometry</dt><dd>{table?.geometry_type ?? '–'}</dd>
			<dt>Features</dt><dd>{fmtNum(d.rows)}{table?.invalid_geom_count ? ` · ${table.invalid_geom_count} invalid` : ''}</dd>
			<dt>Size in PostGIS</dt><dd>{fmtBytes(d.bytes)}</dd>
			<dt>Checksum (source)</dt><dd><code title={table?.checksum ?? ''}>{table?.checksum ? `${table.checksum.slice(0, 12)}…` : '–'}</code></dd>
			<dt>Loaded</dt><dd>{fmtDate(table?.imported_at)}{table?.imported_by ? ` by ${table.imported_by}` : ''}</dd>
			<dt>API keys</dt>
			<dd>
				{#if !d.requires_keys?.length}No key needed{:else}
					{#each d.keys as k (k.key_name)}<code>{k.key_name}</code> <Badge value={k.configured ? 'ok' : 'fail'} title={k.configured ? 'configured' : 'not configured'} /> {/each}
				{/if}
			</dd>
		</dl>
	</section>

	<section class="card" aria-labelledby="fr-h">
		<h2 id="fr-h">Freshness</h2>
		<dl class="facts">
			<dt>Method</dt><dd>{d.freshness_spec?.method ?? 'none'}{d.freshness_spec?.every ? `, every ${d.freshness_spec.every}` : ''}</dd>
			<dt>Verdict</dt><dd><Badge value={latestCheck?.verdict ?? 'unknown'} /> {latestCheck?.detail ?? 'never checked'}</dd>
			<dt>Checked</dt><dd>{fmtAgo(latestCheck?.checked_at)}</dd>
			{#if single}
				<dt>We hold</dt><dd><code>{single.loaded_version ?? '–'}</code>{single.loaded_date ? ` (loaded ${fmtDate(single.loaded_date)})` : ''}</dd>
				<dt>Upstream now</dt>
				<dd>
					<code>{single.upstream_etag ?? single.upstream_last_modified ?? '–'}</code>
					{#if single.upstream_last_modified}<div class="sub">Last-Modified {single.upstream_last_modified} · {fmtBytes(single.upstream_bytes)}</div>{/if}
				</dd>
			{/if}
		</dl>
		<p class="hint">Re-check with <code>make freshness r={d.name}</code>.</p>
	</section>
</div>

<section class="card wide" aria-labelledby="out-h">
	<h2 id="out-h">Outputs &amp; health</h2>
	{#if d.outputs.length}
		<table>
			<thead><tr><th scope="col">Kind</th><th scope="col">Locator</th><th scope="col">Used by</th><th scope="col" class="num">Rows</th><th scope="col">Health</th><th scope="col">Checked</th></tr></thead>
			<tbody>
				{#each d.outputs as o (o.kind + o.locator)}
					<tr>
						<td>{kindLabel[o.kind] ?? o.kind}</td>
						<td>
							{#if o.public_url}<a href={o.public_url} rel="external"><code>{o.locator}</code></a>{:else}<code>{o.locator}</code>{/if}
							{#if o.notes}<div class="sub">{o.notes}</div>{/if}
							{#if o.kind === 'cog' && o.raster}
								{@const r = o.raster}
								<div class="sub">
									{r.width} × {r.height} px, {r.bands} band {r.dtype}, {r.crs ?? 'no CRS'}, {fmtNum(r.resolution[0])} m pixels{#if r.min !== null && r.max !== null}, values {r.min.toFixed(1)} to {r.max.toFixed(1)}{/if}{#if r.nodata !== null}, nodata {r.nodata}{/if}{#if o.bytes}, {fmtBytes(o.bytes)}{/if}
								</div>
							{/if}
						</td>
						<td>{#each o.projects ?? [] as p (p)}<a class="proj" href="/p/{p}">{p}</a>{:else}–{/each}</td>
						<td class="num">{fmtNum(o.row_count)}</td>
						<td><Badge value={o.health} /> <span class="sub">{o.health_detail ?? ''}</span></td>
						<td class="sub">{fmtAgo(o.health_checked_at)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<p class="hint">Re-check with <code>make health-datasets r={d.name}</code>.</p>
	{:else}
		<p class="sub">Nothing loaded yet. Run <code>{cli}</code>.</p>
	{/if}
</section>

{#if d.parts.length > 1}
	<section class="card wide" aria-labelledby="parts-h">
		<h2 id="parts-h">Parts ({d.parts_current}/{d.parts_total} current)</h2>
		<table>
			<thead><tr><th scope="col">Part</th><th scope="col">Upstream</th><th scope="col">Loaded</th><th scope="col" class="num">Rows</th><th scope="col">Status</th></tr></thead>
			<tbody>
				{#each d.parts as p (p.part_key)}
					<tr>
						<td><code>{p.part_key}</code></td>
						<td>{p.upstream_version ?? p.upstream_etag ?? '–'}</td>
						<td>{p.loaded_version ?? '–'}</td>
						<td class="num">{fmtNum(p.row_count)}</td>
						<td><Badge value={p.status} /> <span class="sub">{p.status_detail ?? ''}</span></td>
					</tr>
				{/each}
			</tbody>
		</table>
	</section>
{/if}

<section class="card wide" aria-labelledby="runs-h">
	<h2 id="runs-h">Run history</h2>
	{#if d.runs.length}
		<table>
			<thead><tr><th scope="col">Run</th><th scope="col">Action</th><th scope="col">Status</th><th scope="col">Started</th><th scope="col">Duration</th><th scope="col" class="num">Rows</th><th scope="col" class="num">Downloaded</th><th scope="col">By</th></tr></thead>
			<tbody>
				{#each d.runs as r (r.id)}
					<tr>
						<td><a href="/admin/runs/{r.id}">#{r.id}</a></td>
						<td>{r.action}</td>
						<td><Badge value={r.status} />{#if r.outcome}<div class="sub">{r.outcome}</div>{/if}{#if r.error}<div class="err">{r.error}</div>{/if}</td>
						<td>{fmtDate(r.started_at)}</td>
						<td>{fmtDuration(r.seconds)}</td>
						<td class="num">{fmtNum(r.rows_written)}</td>
						<td class="num">{fmtBytes(r.bytes_downloaded)}</td>
						<td>{r.triggered_by}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{:else}
		<p class="sub">No runs yet.</p>
	{/if}
</section>

<section class="card wide actions" aria-labelledby="act-h">
	<h2 id="act-h">Actions</h2>
	<p>
		Re-download, dry run, rebuild and enable/disable buttons arrive with the job queue (Phase B). Until then, from the
		repo: <code>{cli}</code>. CLI runs appear in the history above.
	</p>
</section>

{#if d.yaml_text}
	<details class="card wide">
		<summary>Recipe <code>{d.yaml_path}</code></summary>
		<pre>{d.yaml_text}</pre>
	</details>
{/if}

<style>
	.crumbs { margin: 0 0 0.5rem; font-size: 0.85rem; }
	.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
	h1 { margin: 0; font-size: 1.45rem; }
	.badges { display: flex; gap: 0.35rem; flex-wrap: wrap; }
	.desc { color: var(--muted); margin: 0.4rem 0 0; }
	.todo { background: #fff8e1; border: 1px solid #f0d68a; border-radius: 8px; padding: 0.5rem 0.75rem; font-size: 0.85rem; }
	.grid { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 0.9fr); gap: 1rem; margin-top: 1rem; }
	.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.9rem 1rem; }
	.card.wide { margin-top: 1rem; }
	h2 { font-size: 0.95rem; margin: 0 0 0.6rem; }
	.facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.3rem 0.8rem; margin: 0.6rem 0 0; font-size: 0.82rem; }
	dt { color: var(--muted); }
	dd { margin: 0; word-break: break-word; }
	table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
	th, td { text-align: left; padding: 0.45rem 0.55rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	th { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	.sub { font-size: 0.75rem; color: var(--muted); }
	.err { font-size: 0.75rem; color: #8a1c14; }
	.hint { font-size: 0.75rem; color: var(--muted); margin: 0.6rem 0 0; }
	.proj { margin-right: 0.4rem; }
	.small { font-size: 0.72rem; padding: 0.05rem 0.4rem; margin-left: 0.3rem; }
	.actions p { margin: 0; font-size: 0.85rem; color: var(--muted); }
	pre { background: #13202c; color: #e6edf3; padding: 0.8rem 1rem; border-radius: 8px; overflow: auto; font-size: 0.8rem; }
	summary { cursor: pointer; font-weight: 600; font-size: 0.9rem; }
	@media (max-width: 1000px) { .grid { grid-template-columns: 1fr; } }
</style>
