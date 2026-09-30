<script lang="ts">
	// One badge for every admin state word (dataset status, health, freshness, run/job status).
	let { value, title }: { value: string | null | undefined; title?: string } = $props();

	const tone = $derived.by(() => {
		switch (value) {
			case 'ok':
			case 'current':
			case 'succeeded':
				return 'good';
			case 'warn':
			case 'stale':
			case 'queued':
			case 'cancel_requested':
				return 'warn';
			case 'running':
			case 'loading':
				return 'info';
			case 'fail':
			case 'failed':
			case 'unhealthy':
			case 'error':
				return 'bad';
			default:
				return 'neutral';
		}
	});
</script>

<span class="badge {tone}" {title}>{value ?? 'unknown'}</span>

<style>
	.badge {
		display: inline-block;
		padding: 0.05rem 0.5rem;
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 600;
		white-space: nowrap;
		border: 1px solid transparent;
	}
	.good { background: #d9f2e3; color: #11552a; border-color: #a9dcbd; }
	.warn { background: #fff1cc; color: #6b4700; border-color: #f0d68a; }
	.info { background: #dbeafe; color: #1e3a8a; border-color: #b7cff7; }
	.bad { background: #fde3e1; color: #8a1c14; border-color: #f5b9b3; }
	.neutral { background: #eceff3; color: #3b4652; border-color: #d3d9e0; }
</style>
