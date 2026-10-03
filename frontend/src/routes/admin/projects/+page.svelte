<script lang="ts">
	// Every registered project and where it is managed. Projects saved in the New project wizard can be deleted here;
	// projects defined by files (projects/<slug>/project.json, in git) come back on the next `./mapgen sync`, so they are
	// removed by taking them out of projects/index.json instead.
	import { onMount } from 'svelte';
	import Badge from '$lib/admin/Badge.svelte';
	import SortTh from '$lib/admin/SortTh.svelte';
	import { TableSort } from '$lib/admin/sort.svelte';
	import { api, fmtAgo } from '$lib/admin/api';
	import { title as pageTitle } from '$lib/site';

	interface Row {
		slug: string;
		title: string;
		status: string;
		origin: 'file' | 'api';
		version: number;
		updated_at: string;
		updated_by: string;
		valid: boolean;
		layers: number;
	}

	let rows = $state<Row[]>([]);
	const sort = new TableSort<Row>({
		project: (r) => r.title,
		status: (r) => r.status,
		layers: (r) => r.layers,
		managed: (r) => r.origin,
		updated: (r) => r.updated_at
	});
	let error = $state('');
	let message = $state('');

	async function load() {
		try {
			rows = await api<Row[]>(fetch, '/projects');
		} catch (e) {
			error = (e as Error).message;
		}
	}
	onMount(load);

	async function remove(r: Row) {
		if (!confirm(`Delete the project "${r.title}" (${r.slug})? This removes it from the map hub. Its data and published views stay.`)) return;
		const res = await fetch(`/api/admin/projects/${encodeURIComponent(r.slug)}`, { method: 'DELETE' });
		if (res.ok) {
			message = `Deleted ${r.title}.`;
			error = '';
			await load();
		} else {
			const body = await res.json().catch(() => ({}));
			error = typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`;
		}
	}
</script>

<svelte:head><title>{pageTitle('Projects')}</title></svelte:head>

<h1>Projects</h1>
<p class="lead">
	Every map on the hub. Projects made with <a href="/admin/new">New project</a> live only here and can be deleted.
	Projects defined by files in <code>projects/</code> are managed in git: remove one from <code>projects/index.json</code>
	and run <code>./mapgen sync</code>.
</p>
{#if message}<p class="ok" role="status">{message}</p>{/if}
{#if error}<p class="err" role="alert">{error}</p>{/if}

<div class="table-wrap">
	<table>
		<thead>
			<tr>
					<SortTh {sort} key="project">Project</SortTh><SortTh {sort} key="status">Status</SortTh><SortTh {sort} key="layers" class="num">Layers</SortTh>
					<SortTh {sort} key="managed">Managed by</SortTh><SortTh {sort} key="updated">Updated</SortTh><th scope="col"><span class="sr-only">Actions</span></th>
				</tr>
		</thead>
		<tbody>
			{#each sort.apply(rows) as r (r.slug)}
				<tr>
					<td><a href="/p/{r.slug}">{r.title}</a> <span class="sub">{r.slug}</span>{#if !r.valid}<div class="err">has validation errors</div>{/if}</td>
					<td><Badge value={r.status} /></td>
					<td class="num">{r.layers}</td>
					<td>{#if r.origin === 'api'}New project wizard{:else}<code>projects/{r.slug}/</code>{/if}</td>
					<td class="sub">v{r.version} · {fmtAgo(r.updated_at)} · {r.updated_by}</td>
					<td>
						{#if r.origin === 'api'}
							<button type="button" class="danger" onclick={() => remove(r)} aria-label="Delete {r.title}">Delete</button>
						{:else}
							<span class="sub" title="Defined by a file in git; remove it from projects/index.json">in git</span>
						{/if}
					</td>
				</tr>
			{:else}
				<tr><td colspan="6" class="sub">Loading…</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	h1 { margin: 0 0 0.3rem; font-size: 1.4rem; }
	.lead { color: var(--muted); max-width: 80ch; margin: 0 0 1rem; }
	.table-wrap { overflow-x: auto; }
	table { width: 100%; border-collapse: collapse; font-size: 0.88rem; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
	table :global(th), td { text-align: left; padding: 0.5rem 0.7rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	table :global(th.num) { text-align: right; }
	table :global(th) { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); font-weight: 600; }
	.num { text-align: right; }
	.sub { color: var(--muted); font-size: 0.8rem; }
	.ok { color: #1b7837; }
	.err { color: #b42318; font-size: 0.85rem; }
	.danger { font: inherit; font-size: 0.82rem; padding: 0.25rem 0.7rem; border-radius: 6px; border: 1px solid #b42318; color: #b42318; background: var(--surface); cursor: pointer; }
	.danger:hover { background: #fde8e6; }
	.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
