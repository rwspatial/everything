import { defineConfig, devices } from '@playwright/test';

// Runs against the live stack (`make e2e` runs this in the Playwright container on the
// edge network, BASE_URL=http://proxy). Screenshots land in test-results/screens/.
export default defineConfig({
	testDir: './tests',
	timeout: 60_000,
	expect: { timeout: 20_000 },
	fullyParallel: false,
	workers: 1,
	reporter: [['list']],
	outputDir: 'test-results/artifacts',
	use: {
		baseURL: process.env.BASE_URL ?? 'http://localhost:8080',
		viewport: { width: 1360, height: 820 },
		trace: 'retain-on-failure'
	},
	projects: [
		{
			name: 'chromium',
			use: {
				...devices['Desktop Chrome'],
				viewport: { width: 1360, height: 820 },
				// Software WebGL2 (MapLibre 6 requires WebGL2) in a headless container.
				launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] }
			}
		}
	]
});
