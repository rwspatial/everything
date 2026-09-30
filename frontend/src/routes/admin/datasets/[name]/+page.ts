import { error } from '@sveltejs/kit';
import { AdminApiError, api, type DatasetDetail } from '$lib/admin/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	try {
		return { d: await api<DatasetDetail>(fetch, `/datasets/${encodeURIComponent(params.name)}`) };
	} catch (e) {
		error(e instanceof AdminApiError ? e.status : 500, (e as Error).message);
	}
};
