<svelte:head><title>New project · Spatial</title></svelte:head>

<main class="page">
	<h1>Create a project</h1>
	<p class="lead">
		A guided creator (pick a published view, choose a style, preview, save) arrives in <strong>Phase 3</strong>. Until then,
		adding a project takes four steps and <strong>no code changes</strong>:
	</p>

	<ol class="steps">
		<li>
			<h2>Load the data</h2>
			<p>Put the file in <code>data/incoming/</code>, then:</p>
			<pre><code>make inspect f=parcels.gpkg
make import f=parcels.gpkg t=src_cad.parcels</code></pre>
		</li>
		<li>
			<h2>Publish a view</h2>
			<p>tiPG only serves the <code>pub</code> schema. Name views <code>pub.&lt;project&gt;__&lt;layer&gt;</code>:</p>
			<pre><code>CREATE OR REPLACE VIEW pub.flood_risk__parcels AS
SELECT id, parcel_id, zone, geom FROM src_cad.parcels;</code></pre>
			<p>Then <code>make refresh</code> so tiPG picks it up.</p>
		</li>
		<li>
			<h2>Write the manifest</h2>
			<p>Copy <code>projects/world-overview/project.json</code> to <code>projects/flood-risk/project.json</code> and edit the slug, title and layers.</p>
		</li>
		<li>
			<h2>List it</h2>
			<p>Add <code>"flood-risk"</code> to <code>projects/index.json</code> and reload the project page. No rebuild or restart needed.</p>
		</li>
	</ol>

	<p>Full walkthrough: <code>docs/setup/04-data-import.md</code> and <code>docs/setup/05-frontend.md</code>.</p>
</main>

<style>
	.page { max-width: 780px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }
	h1 { margin: 0 0 0.5rem; }
	.lead { color: var(--muted); }
	.steps { padding-left: 1.3rem; display: grid; gap: 1rem; }
	.steps h2 { font-size: 1.05rem; margin: 0 0 0.25rem; }
	.steps p { margin: 0.25rem 0; }
	pre { background: #13202c; color: #e6edf3; padding: 0.75rem 1rem; border-radius: 8px; overflow: auto; font-size: 0.82rem; }
	code { font-size: 0.88em; }
</style>
