<script lang="ts">
	import Viewer from '$lib/components/Viewer.svelte';
	import { title } from '$lib/site';

	let { data } = $props();
</script>

<svelte:head><title>{title(data.manifest.title)}</title></svelte:head>

{#key data.manifest.slug}
	<Viewer manifest={data.manifest} config={data.config} />
{/key}
