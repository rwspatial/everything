import { projectRepository } from '$lib/projects';
import { site } from '$lib/site';
import type { PageLoad } from './$types';

// Landing page: selected work comes from the project manifests, so a new tagged project appears here without code changes.
export const load: PageLoad = async ({ parent, fetch }) => {
	const { config } = await parent();
	try {
		const projects = await projectRepository(config, fetch).list();
		return { featured: projects.filter((p) => !p.error && p.tags.includes(site.featuredTag)), total: projects.length };
	} catch {
		return { featured: [], total: 0 };
	}
};
