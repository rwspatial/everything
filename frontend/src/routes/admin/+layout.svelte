<script lang="ts">
	import { page } from '$app/state';

	let { children } = $props();
	const path = $derived(page.url.pathname);
	const under = (...prefixes: string[]) => prefixes.some((p) => path === p || path.startsWith(`${p}/`));
	const cur = (on: boolean) => (on ? 'page' : undefined);
	// Data: the imported sources (/admin, /admin/datasets/*), the database behind them and the API that serves them.
	const DATA = [
		{ href: '/admin', label: 'Sources & imports', hint: 'recipes, runs, freshness and health', on: () => path === '/admin' || under('/admin/datasets') },
		{ href: '/admin/database', label: 'Database tables & views', hint: 'published views, indexes, sizes', on: () => under('/admin/database') },
		{ href: '/admin/data-api', label: 'Tiles & features API', hint: 'the OGC API (tiPG) that serves the maps', on: () => under('/admin/data-api') }
	];
	const inData = $derived(DATA.some((t) => t.on()));
</script>

<div class="admin">
	<div class="bar">
		<nav aria-label="Admin">
			<span class="title">Admin</span>
			<a class="new" href="/admin/new" aria-current={cur(under('/admin/new'))}><span aria-hidden="true">+</span> New project</a>
			<a href="/admin" aria-current={cur(inData)}>Data</a>
			<a href="/admin/projects" aria-current={cur(under('/admin/projects'))}>Projects</a>
			<a href="/admin/jobs" aria-current={cur(under('/admin/jobs', '/admin/runs'))}>Jobs &amp; runs</a>
			<a href="/admin/analysis" aria-current={cur(under('/admin/analysis'))}>Analysis</a>
			<a href="/admin/methods" aria-current={cur(under('/admin/methods'))}>Methods &amp; sources</a>
		</nav>
	</div>
	{#if inData}
		<nav class="sub" aria-label="Data">
			{#each DATA as t (t.href)}
				<a href={t.href} aria-current={cur(t.on())}><span class="label">{t.label}</span><span class="hint">{t.hint}</span></a>
			{/each}
		</nav>
	{/if}
	{@render children()}
</div>

<style>
	.admin { max-width: 1440px; margin: 0 auto; padding: 1rem 1.5rem 3rem; }
	.bar { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 0.6rem; margin-bottom: 1.2rem; }
	nav { display: flex; align-items: center; gap: 1.2rem; flex-wrap: wrap; }
	.title { font-weight: 700; font-size: 1.05rem; }
	nav a { text-decoration: none; font-size: 0.9rem; padding-bottom: 0.15rem; border-bottom: 2px solid transparent; }
	nav a[aria-current='page'] { border-bottom-color: var(--accent); color: var(--text); font-weight: 600; }
	/* New project: the main action, a filled button rather than a tab. */
	nav a.new { background: var(--accent); color: #fff; font-weight: 600; padding: 0.35rem 0.8rem; border-radius: 999px; border: none; box-shadow: 0 1px 3px rgb(0 0 0 / 0.15); }
	nav a.new:hover { background: var(--accent-strong); color: #fff; }
	nav a.new[aria-current='page'] { color: #fff; box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 30%, transparent); }
	nav a.new span { font-size: 1.05rem; line-height: 1; margin-right: 0.15rem; }
	/* Data sub-tabs. */
	.sub { gap: 0.5rem; margin: -0.6rem 0 1.2rem; }
	.sub a { display: grid; gap: 0.05rem; padding: 0.4rem 0.8rem; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); }
	.sub a[aria-current='page'] { border-color: var(--accent); box-shadow: inset 0 -3px 0 var(--accent); font-weight: 400; }
	.sub .label { font-weight: 600; font-size: 0.88rem; }
	.sub .hint { font-size: 0.74rem; color: var(--muted); }
</style>
