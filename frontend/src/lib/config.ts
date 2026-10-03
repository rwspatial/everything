// Runtime configuration, fetched from /config.json so the same build can point at
// other hosts later (e.g. CloudFront in Phase 6) without rebuilding.
export interface AppConfig {
	/** Absolute base URL of the tiPG API (the proxy strips /tiles). */
	tilesBase: string;
	/** Absolute base URL of the static project manifests (fallback when core-api is unreachable). */
	projectsBase: string;
	/** Absolute base URL of the project registry API (core-api). */
	projectsApi: string;
	/** The public production site (Caddyfile.prod): no admin links, no project creation pages. */
	publicMode: boolean;
}

const defaults = { tilesBase: '/tiles', projectsBase: '/projects', projectsApi: '/api/projects', publicMode: false };

let cached: Promise<AppConfig> | undefined;

export function loadConfig(fetchFn: typeof fetch = fetch): Promise<AppConfig> {
	cached ??= fetchFn('/config.json', { cache: 'no-cache' })
		.then((r) => (r.ok ? r.json() : {}))
		.catch(() => ({}))
		.then((raw: Partial<AppConfig>) => {
			const merged = { ...defaults, ...raw };
			// MapLibre workers need absolute URLs; resolve relative ones against this page.
			return {
				tilesBase: new URL(merged.tilesBase, window.location.origin).href.replace(/\/$/, ''),
				projectsBase: new URL(merged.projectsBase, window.location.origin).href.replace(/\/$/, ''),
				projectsApi: new URL(merged.projectsApi, window.location.origin).href.replace(/\/$/, ''),
				publicMode: merged.publicMode === true
			};
		});
	return cached;
}
