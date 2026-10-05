import { api, type DatasetRow, type MethodSummary } from '$lib/admin/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const [methods, datasets] = await Promise.all([
		api<MethodSummary[]>(fetch, '/methods'),
		api<{ datasets: DatasetRow[] }>(fetch, '/datasets')
	]);
	return { methods, datasets: datasets.datasets };
};
