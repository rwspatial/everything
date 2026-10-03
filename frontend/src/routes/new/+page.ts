import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

// How projects are made is an admin topic: the public site (config.publicMode) has no such page.
export const load: PageLoad = async ({ parent }) => {
	const { config } = await parent();
	if (config.publicMode) error(404, 'Not found');
	return {};
};
