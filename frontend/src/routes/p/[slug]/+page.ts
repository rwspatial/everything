import { error } from '@sveltejs/kit';
import { StaticProjectRepository } from '$lib/projects';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, parent, fetch }) => {
	const { config } = await parent();
	try {
		return { manifest: await new StaticProjectRepository(config.projectsBase, fetch).get(params.slug) };
	} catch (e) {
		error(404, (e as Error).message);
	}
};
