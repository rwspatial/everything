import type { PageLoad } from './$types';

export interface Collection { id: string; title?: string; description?: string | null }

// The tiPG catalogue (OGC API Features + Tiles): every published view and function the maps can read.
export const load: PageLoad = async ({ fetch, parent }) => {
	const { config } = await parent();
	const base = config.tilesBase.replace(/\/$/, '');
	try {
		const r = await fetch(`${base}/collections?f=json`);
		const body = r.ok ? await r.json() : null;
		return { base, collections: (body?.collections ?? []) as Collection[], error: r.ok ? '' : `HTTP ${r.status}` };
	} catch (e) {
		return { base, collections: [] as Collection[], error: (e as Error).message };
	}
};
