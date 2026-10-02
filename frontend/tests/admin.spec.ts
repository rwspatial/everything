import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const shot = (page: Page, name: string) => page.screenshot({ path: `test-results/screens/${name}.png`, fullPage: true });

test('admin pages and API require a login', async ({ request }) => {
	for (const path of ['/admin', '/admin/datasets/ne_lakes', '/api/admin/datasets']) {
		const res = await request.get(path);
		expect(res.status(), path).toBe(401);
		expect(res.headers()['www-authenticate'], path).toContain('Basic');
	}
	// Public site stays public.
	expect((await request.get('/')).status()).toBe(200);
	expect((await request.get('/tiles/collections')).status()).toBe(200);
});

test.describe('signed in', () => {
	test.use({ httpCredentials: { username: process.env.ADMIN_USER ?? 'admin', password: process.env.ADMIN_PASSWORD ?? '' } });

	test('dataset table lists every recipe with status', async ({ page }) => {
		await page.goto('/admin');
		const table = page.getByRole('table');
		for (const title of ['Countries (1:110m)', 'Lakes (1:10m)', 'Populated places (1:110m)', 'Rivers and lake centerlines (1:10m)', 'States and provinces (1:50m)']) {
			await expect(table.getByRole('link', { name: title })).toBeVisible();
		}
		const admin1 = table.getByRole('row', { name: /States and provinces/ });
		await expect(admin1.getByText('ok', { exact: true })).toBeVisible();
		await expect(table.getByRole('row', { name: /Lakes \(1:10m\)/ }).getByText('ok', { exact: true })).toBeVisible();
		await page.getByLabel('Search').fill('ne_lakes');
		await expect(table.getByRole('row')).toHaveCount(2); // header + 1
		await page.getByLabel('Search').fill('');
		await shot(page, 'admin-1-datasets');
	});

	test('dataset detail: footprint map, healthy outputs, run history', async ({ page }) => {
		await page.goto('/admin/datasets/ne_lakes');
		await expect(page.getByRole('heading', { name: 'Lakes (1:10m)' })).toBeVisible();
		await page.waitForFunction(() => window.__adminMap?.ready === true, undefined, { timeout: 30_000 });
		expect(await page.evaluate(() => window.__adminMap!.features)).toBeGreaterThan(0);
		await page.waitForFunction(() => window.__adminMap!.map.loaded(), undefined, { timeout: 30_000 });
		const rendered = await page.evaluate(() => window.__adminMap!.map.queryRenderedFeatures({ layers: ['received-fill'] }).length);
		expect(rendered).toBeGreaterThan(0);
		// The canvas must fill its container (regression: map sized before the grid laid out).
		const sizes = await page.evaluate(() => { const m = window.__adminMap!.map; const c = m.getContainer();
			return [m.getCanvas().clientWidth, c.clientWidth]; });
		expect(Math.abs(sizes[0] - sizes[1])).toBeLessThan(3);

		const outputs = page.getByRole('region', { name: 'Outputs & health' });
		await expect(outputs.getByRole('row')).toHaveCount(4); // header + table, view, collection
		await expect(outputs.getByText('ok', { exact: true })).toHaveCount(3);
		await expect(outputs.getByRole('link', { name: 'hydrology-sketch' }).first()).toBeVisible();
		await expect(page.getByText('No key needed')).toBeVisible();

		const runs = page.getByRole('region', { name: 'Run history' });
		await expect(runs.getByRole('row').nth(1)).toBeVisible();
		await shot(page, 'admin-2-detail');

		await runs.getByRole('link').first().click();
		await expect(page.getByRole('heading', { name: /^Run #\d+/ })).toBeVisible();
		await expect(page.getByText(/Log/)).toBeVisible();
		await shot(page, 'admin-3-run');
	});

	test('Maine raster dataset: COG and TiTiler tile outputs are healthy', async ({ page }) => {
		await page.goto('/admin/datasets/phzm_2023_grid_me');
		await expect(page.getByRole('heading', { name: 'Extreme minimum temperature grid 2023 (Maine)' })).toBeVisible();
		const outputs = page.getByRole('region', { name: 'Outputs & health' });
		await expect(outputs.getByRole('row')).toHaveCount(3); // header + cog, tile URL
		await expect(outputs.getByText('ok', { exact: true })).toHaveCount(2);
		await expect(outputs.getByText(/412 × 628 px, 1 band Float32, EPSG:26919/)).toBeVisible();
		await expect(outputs.getByRole('link', { name: 'maine-lands' }).first()).toBeVisible();
		await page.waitForFunction(() => window.__adminMap?.ready === true, undefined, { timeout: 30_000 });
		expect(await page.evaluate(() => window.__adminMap!.features)).toBeGreaterThan(0);
		await shot(page, 'admin-4-maine-cog');
	});

	test('project creator: pick a Maine view, style it, preview, validate, save, open, delete', async ({ page, request }) => {
		const slug = 'e2e-maine-public-lands';
		await request.delete(`/api/admin/projects/${slug}`); // leftover from an interrupted run
		await page.goto('/admin/new');
		await page.getByLabel('Published view (tiPG collection)').selectOption('pub.maine_lands__public_lands');
		await expect(page.getByText(/fields, geometry MultiPolygon/)).toBeVisible();
		await page.getByLabel('Preset').selectOption('categorical');
		await page.getByLabel('Field', { exact: true }).selectOption('designation');
		await page.getByLabel('Project title').fill('E2E Maine Public Lands');
		await expect(page.getByLabel('Slug (URL and folder name)')).toHaveValue(slug);

		// Live preview: the embedded viewer draws the view with the categorical style.
		const preview = page.getByLabel('Preview');
		await expect(preview.getByText('State Park', { exact: true }).first()).toBeVisible(); // legend from the most common values
		await page.waitForFunction(() => window.__spatial?.ready === true && window.__spatial?.idle === true, undefined, { timeout: 30_000 });
		expect(await page.evaluate(() => window.__spatial!.renderedCount('public-lands'))).toBeGreaterThan(100);

		await page.getByRole('button', { name: 'Validate' }).click();
		const report = page.getByRole('region', { name: 'Validation report' });
		await expect(report).toContainText('Valid: 0 error(s)');
		await expect(report).toContainText('checked schema, rules, database, cogs');
		await shot(page, 'admin-5-new-project');

		await page.getByRole('button', { name: 'Save project' }).click();
		await expect(page.getByRole('status').filter({ hasText: `Saved ${slug}` })).toBeVisible();
		await page.getByRole('link', { name: 'Open the map' }).click();
		await expect(page).toHaveURL(new RegExp(`/p/${slug}`));
		await page.waitForFunction(() => window.__spatial?.idle === true, undefined, { timeout: 30_000 });
		expect(await page.evaluate(() => window.__spatial!.renderedCount('public-lands'))).toBeGreaterThan(100);

		// Saving the same slug again is refused; the wizard project can be deleted, a file-managed one cannot.
		expect((await request.post('/api/admin/projects', { data: await (await request.get(`/api/projects/${slug}`)).json() })).status()).toBe(409);
		expect((await request.delete(`/api/admin/projects/${slug}`)).status()).toBe(204);
		expect((await request.delete('/api/admin/projects/maine-lands')).status()).toBe(409);
	});

	test('project API: invalid manifests fail with specific codes', async ({ request }) => {
		const base = await (await request.get('/api/projects/maine-overview')).json();
		const cases: [string, (m: any) => void][] = [
			['E_SOURCE_TYPE', (m) => (m.layers[0].source.type = 'wms')],
			['E_VIEW_MISSING', (m) => (m.layers[0].source.collection = 'pub.maine_overview__nope')],
			['E_PROPERTY_UNKNOWN', (m) => m.layers[0].source.properties.push('bogus')],
			['E_SCHEMA', (m) => (m.view.center = [-69])]
		];
		for (const [code, mutate] of cases) {
			const m = structuredClone(base);
			m.slug = 'e2e-invalid';
			mutate(m);
			const res = await request.post('/api/admin/projects', { data: m });
			expect(res.status(), code).toBe(422);
			const codes = (await res.json()).detail.errors.map((e: { code: string }) => e.code);
			expect(codes, code).toContain(code);
		}
		// Anonymous writes are refused at both paths.
		expect((await request.post('/api/projects', { data: base })).status()).toBe(405);
	});

	test('jobs page shows recent runs', async ({ page }) => {
		await page.goto('/admin/jobs');
		await expect(page.getByRole('heading', { name: 'Recent runs' })).toBeVisible();
		await expect(page.getByRole('table').getByRole('row').nth(1)).toBeVisible();
	});

	test('accessibility: no serious or critical axe violations', async ({ page }) => {
		for (const path of ['/admin', '/admin/datasets/ne_lakes', '/admin/jobs', '/admin/new']) {
			await page.goto(path);
			if (path.includes('/datasets/')) await page.waitForFunction(() => window.__adminMap?.ready === true);
			const results = await new AxeBuilder({ page }).exclude('.maplibregl-canvas').analyze();
			const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
			expect(serious.map((v) => `${path}: ${v.id} (${v.nodes.length}): ${v.help}`)).toEqual([]);
		}
	});
});
