import { api, type Method } from '$lib/admin/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => ({ m: await api<Method>(fetch, `/methods/${encodeURIComponent(params.id)}`) });
