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

	test('jobs page shows recent runs', async ({ page }) => {
		await page.goto('/admin/jobs');
		await expect(page.getByRole('heading', { name: 'Recent runs' })).toBeVisible();
		await expect(page.getByRole('table').getByRole('row').nth(1)).toBeVisible();
	});

	test('accessibility: no serious or critical axe violations', async ({ page }) => {
		for (const path of ['/admin', '/admin/datasets/ne_lakes', '/admin/jobs']) {
			await page.goto(path);
			if (path.includes('/datasets/')) await page.waitForFunction(() => window.__adminMap?.ready === true);
			const results = await new AxeBuilder({ page }).exclude('.maplibregl-canvas').analyze();
			const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
			expect(serious.map((v) => `${path}: ${v.id} (${v.nodes.length}): ${v.help}`)).toEqual([]);
		}
	});
});
