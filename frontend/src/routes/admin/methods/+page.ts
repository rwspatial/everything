import { api, type MethodSummary } from '$lib/admin/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => ({ methods: await api<MethodSummary[]>(fetch, '/methods') });
