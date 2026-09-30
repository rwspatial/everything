import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev server (`make frontend-dev`) forwards data requests to the running stack.
// Inside the node container BACKEND_URL is http://proxy; on the host it defaults to :8080.
const backend = process.env.BACKEND_URL ?? 'http://localhost:8080';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/tiles': backend,
			'/projects': backend
		}
	}
});
