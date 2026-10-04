<script lang="ts">
	// The one catalogue of maps: what's published, what's being worked on, and (for admins) making a new one.
	// The public site (config.publicMode) only ever receives published maps, so it shows just the first section.
	import { page } from '$app/state';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import { title } from '$lib/site';

	let { data } = $props();
	const publicMode = $derived(page.data.config?.publicMode === true);
	const published = $derived(data.projects.filter((p) => !p.error && p.status === 'ready'));
	const inProgress = $derived(data.projects.filter((p) => p.error || p.status !== 'ready'));
	const initial = (t: string) => t.replace(/^Maine\s+/, '').slice(0, 1);
	const missing = (p: (typeof data.projects)[number]) => p.pendingLayers.length + p.notes.length;
</script>

<svelte:head><title>{title('Maps')}</title></svelte:head>

<main class="hub">
	<header class="intro">
		<h1>Maps</h1>
		<p>Live maps of Maine, served from PostGIS on this site. Open one and click anything.</p>
	</header>

	{#if data.error}
		<p class="load-error" role="alert">Could not load the maps: {data.error}</p>
	{/if}

	<section aria-labelledby="published-title">
		{#if !publicMode}<h2 id="published-title" class="section">Published <span class="count">{published.length}</span></h2>{:else}<h2 id="published-title" class="visually-hidden">Published maps</h2>{/if}
		{#if published.length}
			<ul class="grid" aria-label="Published maps">
				{#each published as p (p.slug)}
					<li>
						<a class="card" href="/p/{p.slug}">
							<span class="thumb" aria-hidden="true">{initial(p.title)}</span>
							<span class="body">
								<strong>{p.title}</strong>
								<span class="desc">{p.description}</span>
								<span class="meta">{p.layerCount} layers · Open map →</span>
							</span>
						</a>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="empty">{publicMode ? 'No maps are published yet.' : 'Nothing published yet: set a project to "ready" to publish it.'}</p>
		{/if}
	</section>

	{#if !publicMode && inProgress.length}
		<section aria-labelledby="progress-title">
			<h2 id="progress-title" class="section">In progress <span class="count">{inProgress.length}</span></h2>
			<p class="hint">Drafts and placeholders. Only you see these; the public site shows published maps only.</p>
			<ul class="rows" aria-label="Maps in progress">
				{#each inProgress as p (p.slug)}
					<li class="row" class:broken={p.error}>
						<div class="row-main">
							{#if p.error}<span class="row-title">{p.title}</span>{:else}<a class="row-title" href="/p/{p.slug}">{p.title}</a>{/if}
							<StatusBadge status={p.error ? 'error' : p.status} />
							<span class="row-meta">{p.layerCount} layer{p.layerCount === 1 ? '' : 's'}{#if p.pendingLayers.length} · {p.pendingLayers.length} to do{/if}</span>
						</div>
						{#if p.error}
							<p class="err">{p.error}</p>
						{:else if missing(p)}
							<details>
								<summary>What's missing</summary>
								<ul>
									{#each p.pendingLayers as l (l.title)}<li><strong>{l.title}:</strong> {l.todo}</li>{/each}
									{#each p.notes as n (n)}<li>{n}</li>{/each}
								</ul>
							</details>
						{/if}
					</li>
				{/each}
			</ul>
		</section>
	{/if}

	{#if !publicMode}
		<aside class="create" aria-label="Create a map">
			<div>
				<strong>Create a map</strong>
				<span>Pick a design and a place for a finished map, or build one from a published view.</span>
			</div>
			<a class="btn" href="/admin/new">New map →</a>
		</aside>
	{/if}
</main>

<style>
	.hub { max-width: 1150px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
	.intro h1 { margin: 0 0 0.3rem; font-size: 1.8rem; }
	.intro p { margin: 0; color: var(--muted); max-width: 62ch; }
	.load-error { background: #fde3e1; color: #8a1c14; padding: 0.6rem 0.9rem; border-radius: 8px; }
	.section { display: flex; align-items: baseline; gap: 0.5rem; font-size: 1.1rem; margin: 2rem 0 0.75rem; }
	.count { font-size: 0.8rem; font-weight: 600; color: var(--muted); background: var(--surface-muted); border: 1px solid var(--border); border-radius: 999px; padding: 0 0.5rem; }
	.hint, .empty { color: var(--muted); font-size: 0.88rem; margin: -0.35rem 0 0.75rem; }

	.grid { list-style: none; padding: 0; margin: 1.25rem 0 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1rem; }
	.section + .grid { margin-top: 0; }
	.card { display: flex; flex-direction: column; height: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; color: var(--text); text-decoration: none; transition: border-color 0.15s, transform 0.15s; }
	.card:hover { border-color: var(--accent); transform: translateY(-2px); color: var(--text); }
	.thumb {
		height: 88px; display: grid; place-items: center; font-size: 2rem; font-weight: 700; color: rgb(255 255 255 / 0.9);
		background-color: #0b6e8a;
		background-image: linear-gradient(rgb(255 255 255 / 0.12) 1px, transparent 1px), linear-gradient(90deg, rgb(255 255 255 / 0.12) 1px, transparent 1px);
		background-size: 22px 22px;
	}
	.body { display: flex; flex-direction: column; gap: 0.4rem; padding: 0.9rem 1rem 1rem; flex: 1; }
	.body strong { font-size: 1.05rem; }
	.desc { color: var(--muted); font-size: 0.88rem; display: -webkit-box; -webkit-line-clamp: 3; line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
	.meta { margin-top: auto; font-size: 0.82rem; font-weight: 600; color: var(--accent-strong); }

	.rows { list-style: none; padding: 0; margin: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	.row { padding: 0.6rem 0.9rem; border-bottom: 1px solid var(--border); }
	.row:last-child { border-bottom: none; }
	.row.broken { background: #fff6f5; }
	.row-main { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 0.75rem; }
	.row-title { font-weight: 600; }
	.row-meta { margin-left: auto; font-size: 0.8rem; color: var(--muted); }
	.err { margin: 0.3rem 0 0; color: #8a1c14; font-size: 0.82rem; word-break: break-word; }
	details { margin-top: 0.3rem; font-size: 0.82rem; }
	summary { cursor: pointer; color: var(--muted); }
	details ul { margin: 0.3rem 0 0; padding-left: 1.1rem; }

	.create { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.75rem; margin-top: 2rem; padding: 0.8rem 1rem; border: 1px dashed var(--border); border-radius: 10px; }
	.create div { display: flex; flex-direction: column; gap: 0.15rem; }
	.create span { color: var(--muted); font-size: 0.88rem; }
	.btn { padding: 0.45rem 0.9rem; border-radius: 8px; font-weight: 600; text-decoration: none; background: var(--accent); color: #fff; }
	.btn:hover { background: var(--accent-strong); color: #fff; }
	@media (prefers-reduced-motion: reduce) { .card { transition: none; } .card:hover { transform: none; } }
</style>
