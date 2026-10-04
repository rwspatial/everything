// Where manifests come from. The registry API (core-api, /api/projects) is the default; the static
// files (projects/<slug>/project.json, served by the proxy) are the fallback when core-api is down.
// Both implement ProjectRepository; routes get one from projectRepository().
import { adapterTypes } from './adapters';
import type { AppConfig } from './config';
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

/** Registry API: summaries are computed server-side, manifests come back exactly as stored. */
export class ApiProjectRepository implements ProjectRepository {
	constructor(
		private base: string,
		private fetchFn: typeof fetch = fetch
	) {}

	private async json<T>(url: string): Promise<T> {
		const res = await this.fetchFn(url, { cache: 'no-cache', headers: { Accept: 'application/json' } });
		if (!res.ok) throw new ManifestError(`${res.status} ${res.statusText} for ${url}`);
		return (await res.json()) as T;
	}

	async list(): Promise<ProjectSummary[]> {
		return (await this.json<{ projects: ProjectSummary[] }>(this.base)).projects;
	}

	async get(slug: string): Promise<ProjectManifest> {
		const m = await this.json<ProjectManifest>(`${this.base}/${encodeURIComponent(slug)}`);
		validateManifest(m, slug);
		return m;
	}
}

/** Try the primary repository; on any failure (core-api down, not registered yet) use the fallback. */
export class FallbackProjectRepository implements ProjectRepository {
	constructor(
		private primary: ProjectRepository,
		private fallback: ProjectRepository
	) {}

	async list(): Promise<ProjectSummary[]> {
		try {
			return await this.primary.list();
		} catch {
			return this.fallback.list();
		}
	}

	async get(slug: string): Promise<ProjectManifest> {
		try {
			return await this.primary.get(slug);
		} catch {
			return this.fallback.get(slug);
		}
	}
}

export function projectRepository(config: AppConfig, fetchFn: typeof fetch = fetch): ProjectRepository {
	return new FallbackProjectRepository(
		new ApiProjectRepository(config.projectsApi, fetchFn),
		new StaticProjectRepository(config.projectsBase, fetchFn)
	);
}

/** Cheap structural checks in the browser. The full contract (JSON Schema + database checks) runs in
 * contracts/validate.py when a project is registered (mapgen) or saved (the /admin/new wizard). */
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

/** The one place a project is about: manifest `place` (quick-map builds since 2026-10-04), else the params of its focus
 * layer (earlier builds). Such projects can run the analyses for that unit (/admin/projects/<slug>). */
export function placeOf(m: ProjectManifest): { unit: string; key: string; name?: string } | null {
	if (m.place) return m.place;
	const params = m.layers.find((l) => l.id === 'focus' && l.source.type === 'tipg-vector')?.source as { params?: Record<string, unknown> } | undefined;
	const unit = params?.params?.unit;
	const key = params?.params?.place;
	return typeof unit === 'string' && (typeof key === 'string' || typeof key === 'number') ? { unit, key: String(key) } : null;
}
