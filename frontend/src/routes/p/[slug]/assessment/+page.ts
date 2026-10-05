import { error } from '@sveltejs/kit';
import { projectRepository } from '$lib/projects';
import type { Assessment } from '$lib/assessment';
import type { PageLoad } from './$types';

// The printable vulnerability assessment of a town project: its map and the latest py.town_vulnerability result.
export const load: PageLoad = async ({ params, parent, fetch }) => {
	const { config } = await parent();
	let manifest;
	try {
		manifest = await projectRepository(config, fetch).get(params.slug);
	} catch (e) {
		error(404, (e as Error).message);
	}
	const r = await fetch(`/api/projects/${params.slug}/assessment`);
	const body = await r.json().catch(() => ({}));
	if (!r.ok) error(r.status, typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`);
	return { manifest, assessment: body.report as Assessment, jobId: body.job_id as number, finished: body.finished_at as string };
};
