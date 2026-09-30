<script lang="ts">
	import Viewer from '$lib/components/Viewer.svelte';

	let { data } = $props();
</script>

<svelte:head><title>{data.manifest.title} · Spatial</title></svelte:head>

{#key data.manifest.slug}
	<Viewer manifest={data.manifest} config={data.config} />
{/key}
