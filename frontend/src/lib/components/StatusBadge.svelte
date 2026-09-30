<script lang="ts">
	type Status = 'stub' | 'draft' | 'ready' | 'todo' | 'error';
	let { status }: { status: Status } = $props();
	const labels: Record<Status, string> = { stub: 'Stub', draft: 'Draft', ready: 'Ready', todo: 'To do', error: 'Error' };
	const hints: Record<Status, string> = {
		stub: 'Placeholder: structure only, mostly incomplete',
		draft: 'Draft: works, some parts still pending',
		ready: 'Ready: complete',
		todo: 'Not configured yet',
		error: 'Could not be loaded'
	};
</script>

<span class="badge {status}" title={hints[status]}>{labels[status]}</span>

<style>
	.badge {
		display: inline-block;
		padding: 0.1rem 0.5rem;
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.02em;
		text-transform: uppercase;
		white-space: nowrap;
		border: 1px solid transparent;
	}
	.stub { background: #eceff3; color: #3b4652; border-color: #d3d9e0; }
	.draft { background: #fff1cc; color: #6b4700; border-color: #f0d68a; }
	.ready { background: #d9f2e3; color: #11552a; border-color: #a9dcbd; }
	.todo { background: #f1eefa; color: #4b3a86; border-color: #d8d0f0; }
	.error { background: #fde3e1; color: #8a1c14; border-color: #f5b9b3; }
</style>
