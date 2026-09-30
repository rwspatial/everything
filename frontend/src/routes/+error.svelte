<script lang="ts">
	import { page } from '$app/state';
</script>

<svelte:head><title>Not found · Spatial</title></svelte:head>

<main class="error">
	<h1>{page.status === 404 ? 'Not found' : 'Something went wrong'}</h1>
	<p>{page.error?.message}</p>
	<p><a href="/">← Back to projects</a></p>
</main>

<style>
	.error { max-width: 700px; margin: 3rem auto; padding: 0 1.5rem; }
	p { color: var(--muted); word-break: break-word; }
</style>
