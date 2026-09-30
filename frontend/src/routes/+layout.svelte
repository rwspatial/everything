<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';

	let { children } = $props();
	// The map viewer uses the whole window and brings its own top bar.
	const fullBleed = $derived(page.route.id?.startsWith('/p/') ?? false);
	const current = (path: string) => (page.url.pathname === path ? 'page' : undefined);
</script>

<a class="skip" href="#content">Skip to content</a>

{#if !fullBleed}
	<header class="site">
		<a class="brand" href="/"><span aria-hidden="true">◈</span> Spatial</a>
		<nav aria-label="Main">
			<a href="/" aria-current={current('/')}>Projects</a>
			<a href="/new" aria-current={current('/new')}>New project</a>
			<a href="/tiles/collections" rel="external">Data API</a>
		</nav>
	</header>
{/if}

<div id="content" class:full={fullBleed}>
	{@render children()}
</div>

<style>
	.site {
		display: flex;
		align-items: center;
		gap: 2rem;
		padding: 0.7rem 1.5rem;
		background: #13202c;
		color: #fff;
	}
	.brand { color: #fff; font-weight: 700; font-size: 1.05rem; text-decoration: none; }
	.brand span { color: #5cc8e6; }
	nav { display: flex; gap: 1.25rem; }
	nav a { color: #d4e1ec; text-decoration: none; font-size: 0.9rem; padding: 0.2rem 0; border-bottom: 2px solid transparent; }
	nav a:hover { color: #fff; }
	nav a[aria-current='page'] { color: #fff; border-bottom-color: #5cc8e6; }
</style>
