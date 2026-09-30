import { loadConfig } from '$lib/config';
import type { LayoutLoad } from './$types';

// Static SPA: rendered in the browser only; adapter-static serves 200.html for every route.
export const ssr = false;
export const prerender = false;
export const trailingSlash = 'never';

export const load: LayoutLoad = async ({ fetch }) => ({ config: await loadConfig(fetch) });
