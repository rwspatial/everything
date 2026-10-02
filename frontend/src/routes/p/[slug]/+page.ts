import { error } from '@sveltejs/kit';
import { projectRepository } from '$lib/projects';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, parent, fetch }) => {
	const { config } = await parent();
	try {
		return { manifest: await projectRepository(config, fetch).get(params.slug) };
	} catch (e) {
		error(404, (e as Error).message);
	}
};
