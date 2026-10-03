<script lang="ts" generics="T">
	// A sortable column header: a button inside the <th>, with aria-sort on the <th> for screen readers.
	import type { Snippet } from 'svelte';
	import type { TableSort } from './sort.svelte';

	let { sort, key, class: cls = '', children }: { sort: TableSort<T>; key: string; class?: string; children: Snippet } = $props();

	const state = $derived(sort.ariaSort(key));
</script>

<th scope="col" class={cls} aria-sort={state}>
	<button type="button" onclick={() => sort.toggle(key)}>
		{@render children()}<span class="arrow" aria-hidden="true">{state === 'ascending' ? '▲' : state === 'descending' ? '▼' : '↕'}</span>
	</button>
</th>

<style>
	button {
		all: unset;
		cursor: pointer;
		display: inline-flex;
		align-items: baseline;
		gap: 0.3em;
		font: inherit;
		color: inherit;
		text-transform: inherit;
		letter-spacing: inherit;
	}
	button:focus-visible { outline: 2px solid var(--accent, #0b6e99); outline-offset: 2px; border-radius: 2px; }
	.arrow { font-size: 0.8em; opacity: 0.45; }
	th[aria-sort='ascending'] .arrow,
	th[aria-sort='descending'] .arrow { opacity: 1; }
	button:hover .arrow { opacity: 0.9; }
</style>
