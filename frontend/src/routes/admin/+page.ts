import { api, type DatasetRow, type Output } from '$lib/admin/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) =>
	api<{ datasets: DatasetRow[]; adhoc: Output[] }>(fetch, '/datasets');
