import { error } from '@sveltejs/kit';
import { AdminApiError, api, type RunDetail } from '$lib/admin/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	try {
		return { run: await api<RunDetail>(fetch, `/runs/${encodeURIComponent(params.id)}`) };
	} catch (e) {
		error(e instanceof AdminApiError ? e.status : 500, (e as Error).message);
	}
};
