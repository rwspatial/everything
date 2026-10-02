import { projectRepository } from '$lib/projects';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ parent, fetch }) => {
	const { config } = await parent();
	try {
		return { projects: await projectRepository(config, fetch).list(), error: null };
	} catch (e) {
		return { projects: [], error: (e as Error).message };
	}
};
