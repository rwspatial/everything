<script lang="ts">
	import { page } from '$app/state';

	let { children } = $props();
	const current = (prefix: string) =>
		(prefix === '/admin' ? page.url.pathname === '/admin' || page.url.pathname.startsWith('/admin/datasets') : page.url.pathname.startsWith(prefix))
			? 'page'
			: undefined;
</script>

<div class="admin">
	<div class="bar">
		<nav aria-label="Admin">
			<span class="title">Admin</span>
			<a href="/admin" aria-current={current('/admin')}>Datasets</a>
			<a href="/admin/jobs" aria-current={current('/admin/jobs') ?? current('/admin/runs')}>Jobs &amp; runs</a>
			<a href="/admin/new" aria-current={current('/admin/new')}>New project</a>
			<a href="/admin/analysis" aria-current={current('/admin/analysis')}>Analysis</a>
		</nav>
		<span class="mode" title="Datasets are read-only here: re-download and rebuild actions arrive with the job queue (Phase B). Projects can be created under New project.">
			datasets read-only
		</span>
	</div>
	{@render children()}
</div>

<style>
	.admin { max-width: 1250px; margin: 0 auto; padding: 1rem 1.5rem 3rem; }
	.bar { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); padding-bottom: 0.6rem; margin-bottom: 1.2rem; }
	nav { display: flex; align-items: baseline; gap: 1.2rem; }
	.title { font-weight: 700; font-size: 1.05rem; }
	nav a { text-decoration: none; font-size: 0.9rem; padding-bottom: 0.15rem; border-bottom: 2px solid transparent; }
	nav a[aria-current='page'] { border-bottom-color: var(--accent); color: var(--text); font-weight: 600; }
	.mode { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 0.1rem 0.55rem; }
</style>
