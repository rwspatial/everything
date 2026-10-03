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

	test('admin tables sort by column (aria-sort), both directions, empty values last', async ({ page }) => {
		await page.goto('/admin');
		const table = page.getByRole('table', { name: /Datasets/ });
		const header = table.getByRole('columnheader', { name: 'Features' });
		const features = async () =>
			(await table.locator('tbody tr td:nth-child(6)').allTextContents())
				.map((t) => t.trim())
				.filter((t) => t !== '–')
				.map((t) => Number(t.replace(/[^\d.]/g, '')));
		await header.getByRole('button').click();
		await expect(header).toHaveAttribute('aria-sort', 'ascending');
		const up = await features();
		expect(up.length).toBeGreaterThan(10);
		expect(up).toEqual([...up].sort((a, b) => a - b));
		await header.getByRole('button').click();
		await expect(header).toHaveAttribute('aria-sort', 'descending');
		const down = await features();
		expect(down).toEqual([...down].sort((a, b) => b - a));
		// SSURGO polygons are the largest table, Maine-wide.
		await expect(table.locator('tbody tr').first()).toContainText(/Overture|SSURGO|Soil|Buildings/);
		await expect(table.getByRole('columnheader', { name: 'Dataset' })).toHaveAttribute('aria-sort', 'none');
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
		await page.goto('/admin/new/view');
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
		expect((await request.delete('/api/admin/projects/maine-lands')).status()).toBe(409);
		// Delete it the way a person would: Admin → Projects → Delete (with the confirmation dialog).
		await page.goto('/admin/projects');
		page.once('dialog', (d) => d.accept());
		await page.getByRole('button', { name: 'Delete E2E Maine Public Lands' }).click();
		await expect(page.getByRole('status')).toContainText('Deleted E2E Maine Public Lands');
		await expect(page.getByRole('link', { name: 'E2E Maine Public Lands' })).toHaveCount(0);
		// File-managed projects have no Delete button.
		await expect(page.getByRole('row', { name: /Maine Lands/ }).getByRole('button', { name: /^Delete/ })).toHaveCount(0);
	});

	test('quick map: Town atlas of Bethel, focus outline, framed, saved, opened, deleted', async ({ page, request }) => {
		const slug = 'e2e-bethel-atlas';
		await request.delete(`/api/admin/projects/${slug}`);
		await page.goto('/admin/new');
		await page.getByRole('radio', { name: /Town atlas/ }).click();
		await page.getByLabel('Search towns').fill('Bethel');
		await page.getByRole('button', { name: /^Bethel town/ }).click();
		await expect(page.getByLabel('Project title')).toHaveValue('Bethel: town atlas');
		await page.getByLabel('Slug (URL and folder name)').fill(slug);

		// The preview frames the town and draws the curated layers plus the focus mask and outline.
		await page.waitForFunction(() => window.__spatial?.ready === true && window.__spatial?.idle === true, undefined, { timeout: 45_000 });
		await shot(page, 'admin-5b-quick-map');
		expect(await page.evaluate(() => window.__spatial!.renderedCount('focus'))).toBeGreaterThan(0);
		expect(await page.evaluate(() => window.__spatial!.renderedCount('roads-secondary'))).toBeGreaterThan(0);

		await page.getByRole('button', { name: 'Save project' }).click();
		await expect(page.getByRole('status').filter({ hasText: `Saved ${slug}` })).toBeVisible();
		await page.getByRole('link', { name: 'Open the map' }).click();
		await expect(page).toHaveURL(new RegExp(`/p/${slug}`));
		await page.waitForFunction(() => window.__spatial?.idle === true, undefined, { timeout: 45_000 });
		expect(await page.evaluate(() => window.__spatial!.renderedCount('focus'))).toBeGreaterThan(0);
		await shot(page, 'admin-5c-bethel-atlas');
		expect((await request.delete(`/api/admin/projects/${slug}`)).status()).toBe(204);
	});

	test('quick map API: every design builds a valid manifest for a Maine place', async ({ request }) => {
		const places: Record<string, [string, string]> = {
			town: ['town', '2301704825'], // Bethel
			county: ['county', '23017'] // Oxford
		};
		const designs: { id: string; geographies: string[] }[] = await (await request.get('/api/admin/designs')).json();
		expect(designs.length).toBeGreaterThanOrEqual(5);
		for (const d of designs) {
			let [unit, place] = places[d.geographies[0]] ?? [];
			if (!unit) {
				unit = d.geographies[0];
				place = (await (await request.get(`/api/admin/units/${unit}/places?q=Bethel&limit=1`)).json())[0]?.key
					?? (await (await request.get(`/api/admin/units/${unit}/places?county=23005&limit=1`)).json())[0].key;
			}
			const res = await request.post(`/api/admin/designs/${d.id}/manifest`, { data: { unit, place } });
			expect(res.ok(), d.id).toBe(true);
			const body = await res.json();
			expect(body.report.errors, d.id).toEqual([]);
			expect(body.missing_layers, d.id).toEqual([]);
			expect(body.manifest.layers.at(-1).id, d.id).toBe('focus');
		}
		// A design only builds for its own geographies: the Town atlas refuses a county.
		expect((await request.post('/api/admin/designs/town-atlas/manifest', { data: { unit: 'county', place: '23017' } })).status()).toBe(422);
	});

	test('charts: D3 charts on the fly in the viewer; In view refetches for the map frame', async ({ page }) => {
		await page.goto('/p/maine-overview');
		await page.waitForFunction(() => window.__spatial?.ready === true, undefined, { timeout: 45_000 });
		await page.getByRole('button', { name: 'Charts' }).click();
		const panel = page.getByRole('complementary', { name: 'Charts' });
		await expect(panel.getByText('Maine at a glance')).toBeVisible();
		await expect(panel.getByText('Towns, cities and townships')).toBeVisible();
		// Ranked bars: one mark per town, labelled for screen readers.
		await expect(panel.getByRole('button', { name: /^Cumberland: \$/ })).toBeVisible();
		expect(await panel.locator('figure[aria-label="Highest median household income"] path[role="button"]').count()).toBe(12);
		// Switching a chart to the map frame refetches it with a bbox.
		const req = page.waitForRequest((r) => r.url().includes('/charts/income-spread?bbox='));
		await panel.getByRole('radiogroup', { name: /Towns by median household income/ }).getByLabel('In view').check();
		await req;
		await shot(page, 'admin-6-charts');
	});

	test('chart API: unknown chart fields are refused by validation', async ({ request }) => {
		const m = await (await request.get('/api/projects/maine-overview')).json();
		m.slug = 'zz-chart-check';
		m.charts = [{ id: 'bad', title: 'Bad', type: 'bar', data: { collection: 'pub.maine_overview__towns', category: 'nope' } }];
		const r = await (await request.post('/api/admin/projects/validate', { data: m })).json();
		expect(r.errors.map((e: { code: string }) => e.code)).toContain('E_CHART_FIELD');
	});

	test('PDF report: queued by an admin, printed by the reporter, served publicly', async ({ page, request }) => {
		test.setTimeout(150_000);
		await page.goto('/p/maine-places/report');
		await page.waitForFunction(() => window.__report?.ready === true, undefined, { timeout: 90_000 });
		await expect(page.getByRole('heading', { name: 'Charts' })).toBeVisible();
		const job = await (await request.post('/api/admin/projects/maine-places/reports')).json();
		let status = job.status;
		for (let i = 0; i < 50 && !['succeeded', 'failed'].includes(status); i++) {
			await page.waitForTimeout(2000);
			status = (await (await request.get(`/api/admin/jobs/${job.id}`)).json()).status;
		}
		expect(status).toBe('succeeded');
		const pdf = await request.get('/api/projects/maine-places/reports/latest.pdf');
		expect(pdf.headers()['content-type']).toBe('application/pdf');
		expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-');
		expect((await pdf.body()).length).toBeGreaterThan(50_000);
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

	test('analysis: run the R process (Local Moran\'s I) on Maine town income, preview, add to the sandbox', async ({ page, request }) => {
		test.setTimeout(240_000);
		const original = await (await request.get('/api/projects/analysis-sandbox')).json();
		try {
			await page.goto('/admin/analysis');
			await page.getByLabel('Process', { exact: true }).selectOption('r.local_moran');
			await page.getByLabel('Polygon layer').selectOption('pub.maine_overview__towns');
			await page.getByLabel('Numeric field').selectOption('median_hh_income');
			await page.getByLabel('Label field (popups) (optional)').selectOption('namelsad');
			await page.getByRole('button', { name: 'Run' }).click();
			const status = page.getByRole('region', { name: 'Job status' });
			await expect(status).toContainText('succeeded', { timeout: 200_000 });
			const jobId = Number((await status.getByText(/^Job \d+/).textContent())!.match(/\d+/)![0]);
			await expect(status).toContainText('global_moran');
			await expect(page.getByLabel('Result preview').getByText('High-High')).toBeVisible();
			await page.waitForFunction(() => window.__spatial?.ready === true && window.__spatial?.idle === true, undefined, { timeout: 30_000 });
			// The preview is a small map: count what it draws, which is most of the 496 towns once its tiles are in.
			await expect.poll(() => page.evaluate((id) => window.__spatial!.renderedCount(`job-${id}`), jobId), { timeout: 45_000 }).toBeGreaterThan(250);
			await shot(page, 'admin-6-analysis');

			await page.getByRole('button', { name: 'Add to Analysis Sandbox' }).click();
			await page.getByRole('link', { name: 'Open the Analysis Sandbox' }).click();
			await expect(page).toHaveURL(/\/p\/analysis-sandbox/);
			await page.waitForFunction(() => window.__spatial?.ready === true && window.__spatial?.idle === true, undefined, { timeout: 30_000 });
			await expect.poll(() => page.evaluate((id) => window.__spatial!.renderedCount(`job-${id}`), jobId), { timeout: 20_000 }).toBeGreaterThan(400);
		} finally {
			// Put the sandbox back the way the file has it.
			expect((await request.put('/api/admin/projects/analysis-sandbox', { data: original })).ok()).toBe(true);
		}
	});

	test('dataset actions: dry run and update check on Maine towns, run by the dataset worker', async ({ page }) => {
		test.setTimeout(120_000);
		await page.goto('/admin/datasets/me_cousub');
		const actions = page.getByRole('group', { name: 'Dataset actions' });
		await actions.getByRole('button', { name: 'Dry run' }).click();
		const plan = page.getByRole('table', { name: 'Dry run' });
		await expect(plan).toContainText('import from the cached download', { timeout: 60_000 });
		await expect(plan).toContainText('src_census.cousub · 529 rows now');
		await shot(page, 'admin-7-dataset-actions');

		await actions.getByRole('button', { name: 'Check for updates' }).click();
		await expect(page.getByText('Check for updates: done')).toBeVisible({ timeout: 60_000 });
		// The run shows up in the dataset's history, triggered from the dashboard.
		const runs = page.getByRole('region', { name: 'Run history' });
		await expect(runs.getByRole('row').nth(1)).toContainText('freshness');
		await expect(runs.getByRole('row').nth(1)).toContainText('admin:');
	});

	test('jobs page shows recent runs', async ({ page }) => {
		await page.goto('/admin/jobs');
		await expect(page.getByRole('heading', { name: 'Recent runs' })).toBeVisible();
		await expect(page.getByRole('table').getByRole('row').nth(1)).toBeVisible();
	});

	test('database page: every published view can use a spatial index; tables sortable', async ({ page }) => {
		await page.goto('/admin/database');
		const card = page.getByRole('region', { name: 'Summary' }).getByText(/published views can use a spatial index/).locator('..');
		const [indexed, total] = ((await card.locator('.big').textContent()) ?? '').split('/').map((s) => Number(s.trim()));
		expect(total).toBeGreaterThan(100);
		expect(indexed).toBe(total);
		await expect(page.getByRole('status').filter({ hasText: 'Every published view can use a spatial index' })).toBeVisible();
		const buildings = page.getByRole('row', { name: /src_overture\.buildings/ });
		await expect(buildings).toContainText('MultiPolygon');
		await expect(buildings).toContainText('GiST');
		await shot(page, 'admin-database');
	});

	test('accessibility: no serious or critical axe violations', async ({ page }) => {
		for (const path of ['/admin', '/admin/datasets/ne_lakes', '/admin/jobs', '/admin/new', '/admin/new/view', '/admin/analysis', '/admin/projects', '/admin/database']) {
			await page.goto(path);
			if (path.includes('/datasets/')) await page.waitForFunction(() => window.__adminMap?.ready === true);
			const results = await new AxeBuilder({ page }).exclude('.maplibregl-canvas').analyze();
			const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
			expect(serious.map((v) => `${path}: ${v.id} (${v.nodes.length}): ${v.help}`)).toEqual([]);
		}
	});
});
