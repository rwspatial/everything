// Where manifests come from. Phase 2 reads static JSON (projects/<slug>/project.json,
// served by the proxy). Phase 3 swaps in a core-api implementation of the same interface.
import { adapterTypes } from './adapters';
import type { ProjectManifest, ProjectSummary } from './types';

export interface ProjectRepository {
	list(): Promise<ProjectSummary[]>;
	get(slug: string): Promise<ProjectManifest>;
}

export class ManifestError extends Error {}

export class StaticProjectRepository implements ProjectRepository {
	constructor(
		private base: string,
		private fetchFn: typeof fetch = fetch
	) {}

	private async json<T>(url: string): Promise<T> {
		const res = await this.fetchFn(url, { cache: 'no-cache' });
		if (!res.ok) throw new ManifestError(`${res.status} ${res.statusText} for ${url}`);
		try {
			return (await res.json()) as T;
		} catch {
			throw new ManifestError(`${url} is not valid JSON`);
		}
	}

	async list(): Promise<ProjectSummary[]> {
		const index = await this.json<{ projects: string[] }>(`${this.base}/index.json`);
		return Promise.all(
			index.projects.map((slug) =>
				this.get(slug).then(summarize, (e: Error) => ({
					slug,
					title: slug,
					status: 'stub' as const,
					description: '',
					tags: [],
					layerCount: 0,
					pendingLayers: [],
					notes: [],
					error: e.message
				}))
			)
		);
	}

	async get(slug: string): Promise<ProjectManifest> {
		const m = await this.json<ProjectManifest>(`${this.base}/${encodeURIComponent(slug)}/project.json`);
		validateManifest(m, slug);
		return m;
	}
}

/** Structural checks that catch authoring mistakes early; Phase 3 replaces this with JSON Schema. */
export function validateManifest(m: ProjectManifest, slug: string): void {
	const fail = (msg: string) => {
		throw new ManifestError(`projects/${slug}/project.json: ${msg}`);
	};
	if (m.manifestVersion !== 1) fail('manifestVersion must be 1');
	if (m.slug !== slug) fail(`slug "${m.slug}" does not match its folder "${slug}"`);
	if (!['stub', 'draft', 'ready'].includes(m.status)) fail(`unknown status "${m.status}"`);
	if (!m.view || !Array.isArray(m.view.center) || typeof m.view.zoom !== 'number') fail('view needs center and zoom');
	if (!Array.isArray(m.layers)) fail('layers must be an array');
	const seen = new Set<string>();
	for (const l of m.layers) {
		if (!l.id || !/^[a-z0-9_-]+$/.test(l.id)) fail(`layer id "${l.id}" must be lowercase letters, digits, _ or -`);
		if (seen.has(l.id)) fail(`duplicate layer id "${l.id}"`);
		seen.add(l.id);
		if (!adapterTypes.includes(l.source?.type)) {
			fail(`layer "${l.id}": unknown source.type "${l.source?.type}" (known: ${adapterTypes.join(', ')})`);
		}
	}
}

export function summarize(m: ProjectManifest): ProjectSummary {
	return {
		slug: m.slug,
		title: m.title,
		status: m.status,
		description: m.description ?? '',
		tags: m.tags ?? [],
		layerCount: m.layers.length,
		pendingLayers: m.layers
			.filter((l) => l.status === 'todo')
			.map((l) => ({ title: l.title, todo: l.todo ?? 'Not configured yet.' })),
		notes: m.notes ?? []
	};
}
