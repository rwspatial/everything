<script lang="ts">
	// LaTeX via KaTeX, loaded on first use so only the methods pages pay for it.
	import 'katex/dist/katex.min.css';

	let { tex, display = true }: { tex: string; display?: boolean } = $props();
	let html = $state('');

	$effect(() => {
		const src = tex;
		void import('katex').then(({ default: katex }) => {
			html = katex.renderToString(src, { displayMode: display, throwOnError: false, output: 'htmlAndMathml' });
		});
	});
</script>

{#if html}<span class="tex">{@html html}</span>{:else}<code>{tex}</code>{/if}

<style>
	.tex :global(.katex-display) { margin: 0.4rem 0 0; overflow-x: auto; overflow-y: hidden; }
</style>
