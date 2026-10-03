<script lang="ts">
	let { data } = $props();
</script>

<svelte:head><title>Methods · Admin</title></svelte:head>

<h1>Methods</h1>
<p class="lead">
	How the derived layers are calculated: inputs, steps, the parameters and why they were chosen, and known limits. Each
	is a file in <code>docs/methods/</code>.
</p>

{#if data.methods.length}
	<ul class="list">
		{#each data.methods as m (m.id)}
			<li>
				<a href="/admin/methods/{m.id}">{m.title}</a>
				{#if m.project}<span class="sub">{m.project}{m.layer ? ` · ${m.layer}` : ''}</span>{/if}
				<p>{m.summary}</p>
			</li>
		{/each}
	</ul>
{:else}
	<p class="sub">No methods yet. Add a JSON file to <code>docs/methods/</code>.</p>
{/if}

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.5rem; }
	.lead { color: var(--muted); margin: 0 0 1rem; max-width: 75ch; }
	.list { list-style: none; padding: 0; margin: 0; display: grid; gap: 0.8rem; }
	.list li { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 0.8rem 1rem; }
	.list a { font-weight: 600; }
	.list p { margin: 0.3rem 0 0; font-size: 0.9rem; max-width: 80ch; }
	.sub { font-size: 0.75rem; color: var(--muted); margin-left: 0.5rem; }
	code { font-size: 0.8rem; }
</style>
