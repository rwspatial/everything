<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import { site } from '$lib/site';

	let { children } = $props();
	// The map viewer uses the whole window and brings its own top bar.
	const fullBleed = $derived(page.route.id?.startsWith('/p/') ?? false);
	const current = (path: string) => (page.url.pathname === path ? 'page' : undefined);
</script>

<a class="skip" href="#content">Skip to content</a>

{#if !fullBleed}
	<header class="site">
		<a class="brand" href="/"><span aria-hidden="true">◈</span> {site.studio}</a>
		<nav aria-label="Main">
			<a href="/#work">Work</a>
			<a href="/maps" aria-current={current('/maps')}>Maps</a>
			<a href="/about" aria-current={current('/about')}>About &amp; contact</a>
			{#if !page.data.config?.publicMode}
				<a href="/admin" aria-current={page.url.pathname.startsWith('/admin') ? 'page' : undefined}>Admin</a>
			{/if}
			<a href="/tiles/" rel="external">Data API</a>
		</nav>
	</header>
{/if}

<div id="content" class:full={fullBleed}>
	{@render children()}
</div>

{#if !fullBleed}
	<footer class="site-foot">
		<span>© {new Date().getFullYear()} {site.person || site.studio} · {site.location}</span>
		<nav aria-label="Developer">
			<a href="/tiles/" rel="external">Data API</a>
			{#if !page.data.config?.publicMode}<a href="/new" aria-current={current('/new')}>Add a project</a>{/if}
		</nav>
	</footer>
{/if}

<style>
	.site {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 2rem;
		padding: 0.7rem 1.5rem;
		background: #13202c;
		color: #fff;
	}
	.brand { color: #fff; font-weight: 700; font-size: 1.05rem; text-decoration: none; }
	.brand span { color: #5cc8e6; }
	nav { display: flex; flex-wrap: wrap; gap: 0.4rem 1.25rem; }
	nav a { color: #d4e1ec; text-decoration: none; font-size: 0.9rem; padding: 0.2rem 0; border-bottom: 2px solid transparent; }
	nav a:hover { color: #fff; }
	nav a[aria-current='page'] { color: #fff; border-bottom-color: #5cc8e6; }
	.site-foot {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 0.5rem 2rem;
		padding: 1.2rem 1.5rem;
		font-size: 0.8rem;
		color: var(--muted);
		border-top: 1px solid var(--border);
	}
	.site-foot nav a { color: var(--muted); font-size: 0.8rem; }
</style>
