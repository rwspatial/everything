import { projectRepository } from '$lib/projects';
import { site } from '$lib/site';
import type { PageLoad } from './$types';

// Landing page: selected work comes from the project manifests, so a new tagged project appears here without code changes.
export const load: PageLoad = async ({ parent, fetch }) => {
	const { config } = await parent();
	try {
		const projects = await projectRepository(config, fetch).list();
		// Three published maps up front; the Maps page is the full catalogue (published, in progress, create).
		const published = projects.filter((p) => !p.error && p.status === 'ready');
		const featured = published.filter((p) => p.tags.includes(site.featuredTag));
		return { featured: (featured.length ? featured : published).slice(0, 3), total: published.length };
	} catch {
		return { featured: [], total: 0 };
	}
};
