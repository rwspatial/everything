<script lang="ts">
	import { title } from '$lib/site';
</script>

<svelte:head><title>{title('New project')}</title></svelte:head>

<main class="page">
	<h1>Create a project</h1>
	<p class="lead">Two ways, one result: both write the same project manifest and run the same checks.</p>

	<section class="way">
		<h2>In the browser</h2>
		<p>
			<a class="button" href="/admin/new">Open the project creator</a> (admin login): pick a published view, choose a
			style preset, check the live preview, save.
		</p>
	</section>

	<section class="way">
		<h2>From the command line</h2>
		<ol class="steps">
			<li>
				<p>Load the data, with a recipe or a one-off file:</p>
				<pre><code>make import-recipe r=me_cousub
make import f=parcels.gpkg t=src_cad.parcels</code></pre>
			</li>
			<li>
				<p>Scaffold the project (manifest + the SQL for its first view):</p>
				<pre><code>./mapgen new maine-parcels --title "Maine Parcels" --layer parcels --from src_cad.parcels</code></pre>
			</li>
			<li>
				<p>Edit <code>projects/maine-parcels/sql/010_parcels.sql</code> and the layer style, then publish:</p>
				<pre><code>./mapgen apply maine-parcels</code></pre>
				<p>That validates the manifest, creates the <code>pub</code> view, refreshes tiPG and registers the project.</p>
			</li>
		</ol>
	</section>

	<p>Full walkthrough: <code>docs/setup/07-projects.md</code>.</p>
</main>

<style>
	.page { max-width: 780px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
	h1 { margin: 0 0 0.5rem; }
	.lead { color: var(--muted); }
	.steps { padding-left: 1.3rem; display: grid; gap: 1rem; }
	.way { margin-top: 1.4rem; }
	.way h2 { font-size: 1.1rem; margin: 0 0 0.3rem; }
	.button { display: inline-block; background: var(--accent); color: #fff; padding: 0.45rem 0.9rem; border-radius: 6px; text-decoration: none; }
	.steps p { margin: 0.25rem 0; }
	pre { background: #13202c; color: #e6edf3; padding: 0.75rem 1rem; border-radius: 8px; overflow: auto; font-size: 0.82rem; }
	code { font-size: 0.88em; }
</style>
