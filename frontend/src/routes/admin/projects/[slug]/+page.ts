import { api, type ProjectAnalyses } from '$lib/admin/api';
import { placeOf } from '$lib/projects';
import type { ProjectManifest } from '$lib/types';
import type { PageLoad } from './$types';

// The project workspace: its map, and the analyses of the place it is about (manifest `place`).
export const load: PageLoad = async ({ fetch, params }) => {
	const res = await fetch(`/api/projects/${encodeURIComponent(params.slug)}`, { cache: 'no-store' });
	if (!res.ok) throw new Error(`${res.status} ${res.statusText}: no project ${params.slug}`);
	const manifest = (await res.json()) as ProjectManifest;
	const analyses = placeOf(manifest) ? await api<ProjectAnalyses>(fetch, `/projects/${encodeURIComponent(params.slug)}/analyses`) : null;
	return { slug: params.slug, manifest, analyses };
};
