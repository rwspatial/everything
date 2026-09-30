import { StaticProjectRepository } from '$lib/projects';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent, fetch }) => {
	const { config } = await parent();
	try {
		return { projects: await new StaticProjectRepository(config.projectsBase, fetch).list(), error: null };
	} catch (e) {
		return { projects: [], error: (e as Error).message };
	}
};
