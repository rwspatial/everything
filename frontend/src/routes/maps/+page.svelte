<script lang="ts">
	import { page } from '$app/state';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import { title } from '$lib/site';

	let { data } = $props();
	const counts = $derived({
		total: data.projects.length,
		pending: data.projects.reduce((n, p) => n + p.pendingLayers.length, 0)
	});
</script>

<svelte:head><title>{title('Map projects')}</title></svelte:head>

<main class="hub">
	<section class="intro">
		<h1>Map projects</h1>
		<p>
			Each project is a set of PostGIS views plus a small manifest. Open one to explore its layers, or see what's still
			missing in the placeholders.
		</p>
		{#if counts.total}
			<p class="summary">{counts.total} projects · {counts.pending} layers still to do</p>
		{/if}
	</section>

	{#if data.error}
		<p class="load-error" role="alert">Could not load the project list: {data.error}</p>
	{/if}

	<ul class="grid" aria-label="Projects">
		{#each data.projects as p (p.slug)}
			<li class="card" class:broken={p.error}>
				<div class="thumb {p.status}" aria-hidden="true"><span>{p.title.slice(0, 1)}</span></div>
				<div class="body">
					<div class="head">
						<h2>{#if p.error}{p.title}{:else}<a href="/p/{p.slug}">{p.title}</a>{/if}</h2>
						<StatusBadge status={p.error ? 'error' : p.status} />
					</div>
					{#if p.error}
						<p class="err">{p.error}</p>
					{:else}
						<p class="desc">{p.description || 'No description yet.'}</p>
						{#if p.tags.length}
							<ul class="tags" aria-label="Tags">{#each p.tags as t (t)}<li>{t}</li>{/each}</ul>
						{/if}
						<p class="meta">
							{p.layerCount} layer{p.layerCount === 1 ? '' : 's'}
							{#if p.pendingLayers.length}· <strong>{p.pendingLayers.length} of {p.layerCount} pending</strong>{/if}
						</p>
						{#if p.pendingLayers.length || p.notes.length}
							<details>
								<summary>What's missing?</summary>
								<ul>
									{#each p.pendingLayers as l (l.title)}<li><strong>{l.title}:</strong> {l.todo}</li>{/each}
									{#each p.notes as n (n)}<li>{n}</li>{/each}
								</ul>
							</details>
						{/if}
						<a class="open" href="/p/{p.slug}">Open map →<span class="visually-hidden">: {p.title}</span></a>
					{/if}
				</div>
			</li>
		{/each}
		{#if !page.data.config?.publicMode}
			<li class="card new">
				<div class="body">
					<h2><a href="/new">Create a project</a></h2>
					<p class="desc">Pick a design and a place, or build a map from a published view (admin).</p>
					<a class="open" href="/new">How to add one →</a>
				</div>
			</li>
		{/if}
	</ul>
</main>

<style>
	.hub { max-width: 1150px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
	.intro h1 { margin: 0 0 0.4rem; font-size: 1.8rem; }
	.intro p { margin: 0; color: var(--muted); max-width: 60ch; }
	.intro .summary { margin-top: 0.5rem; font-size: 0.85rem; }
	.load-error { background: #fde3e1; color: #8a1c14; padding: 0.6rem 0.9rem; border-radius: 8px; }
	.grid {
		list-style: none;
		padding: 0;
		margin: 1.75rem 0 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
		gap: 1.25rem;
	}
	.card {
		display: flex;
		flex-direction: column;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 12px;
		overflow: hidden;
		box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
	}
	.card.new { border-style: dashed; background: transparent; justify-content: center; }
	.card.broken { border-color: #f5b9b3; }
	.thumb {
		height: 110px;
		display: grid;
		place-items: center;
		font-size: 2.2rem;
		font-weight: 700;
		color: rgb(255 255 255 / 0.9);
		background-image:
			linear-gradient(rgb(255 255 255 / 0.12) 1px, transparent 1px),
			linear-gradient(90deg, rgb(255 255 255 / 0.12) 1px, transparent 1px);
		background-size: 22px 22px;
	}
	.thumb.ready { background-color: #177245; }
	.thumb.draft { background-color: #0b6e8a; }
	.thumb.stub { background-color: #5b6878; }
	.body { padding: 1rem 1.1rem 1.1rem; display: flex; flex-direction: column; gap: 0.5rem; flex: 1; }
	.head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
	h2 { font-size: 1.1rem; margin: 0; }
	h2 a { color: var(--text); text-decoration: none; }
	h2 a:hover { color: var(--accent-strong); text-decoration: underline; }
	.desc { margin: 0; color: var(--muted); font-size: 0.9rem; }
	.err { margin: 0; color: #8a1c14; font-size: 0.85rem; word-break: break-word; }
	.tags { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 0.3rem; }
	.tags li { font-size: 0.72rem; background: var(--surface-muted); border: 1px solid var(--border); border-radius: 999px; padding: 0.05rem 0.5rem; color: var(--muted); }
	.meta { margin: 0; font-size: 0.8rem; color: var(--muted); }
	.meta strong { color: #6b4700; }
	details { font-size: 0.82rem; background: var(--surface-muted); border-radius: 8px; padding: 0.4rem 0.6rem; }
	summary { cursor: pointer; font-weight: 600; }
	details ul { margin: 0.4rem 0 0; padding-left: 1.1rem; }
	.open { margin-top: auto; align-self: flex-start; font-weight: 600; font-size: 0.9rem; }
</style>
