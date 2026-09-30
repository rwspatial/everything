import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
export default {
	preprocess: vitePreprocess(),
	kit: {
		// Pure static SPA: every route is rendered in the browser from 200.html.
		// The same build can later be hosted on S3 + CloudFront (Phase 6).
		adapter: adapter({ fallback: '200.html' })
	}
};
