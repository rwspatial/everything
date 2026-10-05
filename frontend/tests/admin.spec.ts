import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const shot = (page: Page, name: string) => page.screenshot({ path: `test-results/screens/${name}.png`, fullPage: true });

test('admin pages and API require a login', async ({ request }) => {
	for (const path of ['/admin', '/admin/datasets/me_boat_launches', '/api/admin/datasets']) {
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
		for (const title of ['Countries (1:110m)', 'Populated places (1:110m)', 'States and provinces (1:50m)', 'Boat launches (Maine)']) {
			await expect(table.getByRole('link', { name: title })).toBeVisible();
		}
		const admin1 = table.getByRole('row', { name: /States and provinces/ });
		await expect(admin1.getByText('ok', { exact: true })).toBeVisible();
		await expect(table.getByRole('row', { name: /Boat launches \(Maine\)/ }).getByText('ok', { exact: true })).toBeVisible();
		await page.getByLabel('Search').fill('me_boat_launches');
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
		await page.goto('/admin/datasets/me_boat_launches');
		await expect(page.getByRole('heading', { name: 'Boat launches (Maine)' })).toBeVisible();
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
		await expect(outputs.getByRole('link', { name: 'maine-coast' }).first()).toBeVisible();
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
		// Every design, for every kind of place it serves (a design may vary its layers and charts by place).
		for (const d of designs) {
			for (const g of d.geographies) {
				let [unit, place] = places[g] ?? [];
				if (!unit) {
					unit = g;
					place = (await (await request.get(`/api/admin/units/${unit}/places?q=Bethel&limit=1`)).json())[0]?.key
						?? (await (await request.get(`/api/admin/units/${unit}/places?county=23005&limit=1`)).json())[0].key;
				}
				const res = await request.post(`/api/admin/designs/${d.id}/manifest`, { data: { unit, place } });
				expect(res.ok(), `${d.id} ${g}`).toBe(true);
				const body = await res.json();
				expect(body.report.errors, `${d.id} ${g}`).toEqual([]);
				expect(body.missing_layers, `${d.id} ${g}`).toEqual([]);
				expect(body.manifest.layers.at(-1).id, `${d.id} ${g}`).toBe('focus');
			}
		}
		// The Demographics design: towns for a county, the tract layers for a tract.
		const county = await (await request.post('/api/admin/designs/demographics/manifest', { data: { unit: 'county', place: '23017' } })).json();
		expect(county.manifest.layers.map((l: { id: string }) => l.id)).toEqual(expect.arrayContaining(['towns', 'town-boundaries']));
		expect(county.manifest.title).toBe('Oxford County: demographics');
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

	test('charts: Maine habitat charts (rare animals, tidal habitat, vernal pools, at-risk scores); stippled blocks', async ({ page }) => {
		await page.goto('/p/maine-habitat');
		await page.waitForFunction(() => window.__spatial?.ready === true, undefined, { timeout: 45_000 });
		await page.getByRole('button', { name: 'Charts' }).click();
		const panel = page.getByRole('complementary', { name: 'Charts' });
		await expect(panel.getByText('Undeveloped habitat blocks')).toBeVisible();
		await expect(panel.getByRole('button', { name: /^Endangered: / })).toBeVisible();
		await expect(panel.getByRole('button', { name: /^Piping Plover: / })).toBeVisible();
		expect(await panel.locator('figure[aria-label="Most-recorded rare animals"] path[role="button"]').count()).toBe(12);
		await expect(panel.getByRole('button', { name: /^Significant: / })).toBeVisible();
		await shot(page, 'habitat-charts');
		// The stipple on undeveloped blocks, close up (softer dots: half strength, 0.75 px).
		await page.evaluate(() => window.__spatial!.map!.jumpTo({ center: [-69.05, 45.2], zoom: 12 }));
		await page.waitForFunction(() => window.__spatial?.idle === true, undefined, { timeout: 30_000 });
		await shot(page, 'habitat-stipple');
	});

	test('charts: every published map has at least one chart, and every chart returns data', async ({ page, request }) => {
		test.setTimeout(120_000);
		const { projects }: { projects: { slug: string; status: string }[] } = await (await request.get('/api/projects')).json();
		const published = projects.filter((p) => p.status === 'ready');
		expect(published.length).toBeGreaterThan(10);
		for (const p of published) {
			const m = await (await request.get(`/api/projects/${p.slug}`)).json();
			expect(m.charts?.length ?? 0, `${p.slug} has no charts`).toBeGreaterThan(0);
			for (const c of m.charts) {
				const r = await request.get(`/api/projects/${p.slug}/charts/${c.id}`);
				expect(r.status(), `${p.slug}/${c.id}`).toBe(200);
				const d = await r.json();
				expect((d.rows?.length ?? 0) + (d.bins?.length ?? 0) + (d.stats?.length ?? 0) + (d.points?.length ?? 0), `${p.slug}/${c.id} is empty`).toBeGreaterThan(0);
			}
		}
		// Raster maps chart class areas (src_raster.class_area): Maine Land Cover.
		await page.goto('/p/maine-landcover');
		await page.waitForFunction(() => window.__spatial?.ready === true, undefined, { timeout: 45_000 });
		await page.getByRole('button', { name: 'Charts' }).click();
		const panel = page.getByRole('complementary', { name: 'Charts' });
		await expect(panel.getByRole('button', { name: /^Forest: / })).toBeVisible();
		await expect(panel.getByRole('button', { name: /^Potatoes: / })).toBeVisible();
		await shot(page, 'landcover-charts');
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

	test('admin nav: New project first, one Data section with three tabs; the API tab lists the collections', async ({ page }) => {
		await page.goto('/admin');
		const nav = page.getByRole('navigation', { name: 'Admin' });
		await expect(nav.getByRole('link').first()).toHaveText(/New project/);
		await expect(nav.getByRole('link', { name: 'Data', exact: true })).toHaveAttribute('aria-current', 'page');
		const data = page.getByRole('navigation', { name: 'Data' });
		await expect(data.getByRole('link')).toHaveCount(3);
		await data.getByRole('link', { name: /Tiles & features API/ }).click();
		await expect(page.getByRole('heading', { name: 'Tiles & features API' })).toBeVisible();
		await expect(page.getByRole('link', { name: 'pub.maine_water__stream_gauges' })).toHaveAttribute('href', /\/tiles\/collections\/pub\.maine_water__stream_gauges$/);
		await expect(page.getByRole('navigation', { name: 'Data' }).getByRole('link', { name: /Tiles & features API/ })).toHaveAttribute('aria-current', 'page');
		await shot(page, 'admin-data-api');
		// The site's main nav does not offer the Data API.
		await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: /Data API|Tiles/ })).toHaveCount(0);
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

	test('methods: settlements method shows steps, LaTeX, live counts and its SQL', async ({ page }) => {
		await page.goto('/admin/methods');
		await expect(page.getByRole('heading', { name: 'Methods & sources', level: 1 })).toBeVisible();
		// Sources: every loaded dataset with its attribution, grouped by publisher, filterable.
		const sources = page.getByRole('region', { name: 'Sources' });
		await expect(sources.getByRole('heading', { name: /U\.S\. Census Bureau/ })).toBeVisible();
		await expect(sources.getByText('© OpenStreetMap contributors, Overture Maps Foundation').first()).toBeVisible();
		await page.getByLabel('Filter sources').fill('hardiness');
		await expect(sources.getByRole('link', { name: /hardiness/i }).first()).toBeVisible();
		await expect(sources.getByRole('heading', { name: /U\.S\. Census Bureau/ })).toHaveCount(0);
		await shot(page, 'admin-methods-sources');
		await page.getByLabel('Filter sources').fill('');
		await page.getByRole('link', { name: 'Settlements (built-up areas)' }).click();
		await expect(page.getByRole('heading', { name: 'Settlements (built-up areas)' })).toBeVisible();
		await expect(page.getByText('rows in pub.maine_places__settlements')).toBeVisible();
		await expect(page.locator('.katex').first()).toBeVisible();
		await expect(page.getByRole('row', { name: /Dense cell/ })).toContainText('6 buildings/ha');
		await expect(page.getByRole('heading', { name: 'References' })).toBeVisible();
		await expect(page.getByRole('link', { name: /Degree of Urbanisation/ }).first()).toBeVisible();
		await page.getByText('SQL:').click();
		await expect(page.locator('pre')).toContainText('ST_ClusterDBSCAN');
		await shot(page, 'admin-methods-settlements');
	});

	test('vulnerability assessment: Castine from the design, run, printable assessment in the program order', async ({ page, request }) => {
		test.setTimeout(300_000);
		const slug = 'e2e-castine-vulnerability';
		await request.delete(`/api/admin/projects/${slug}`);
		const town = (await (await request.get('/api/admin/units/town/places?q=Castine&limit=5')).json()).find((r: { short_name: string }) => r.short_name === 'Castine');
		const built = await (await request.post('/api/admin/designs/town-vulnerability/manifest', { data: { unit: 'town', place: town.key, slug } })).json();
		expect(built.manifest.layers.map((l: { id: string }) => l.id)).toEqual(expect.arrayContaining(['slr-scenarios', 'tracts-svi', 'flood-zones']));
		expect((await request.post('/api/admin/projects', { data: { ...built.manifest, slug } })).status()).toBe(201);
		try {
			const job = await (await request.post(`/api/admin/projects/${slug}/analyses`, { data: { process: 'py.town_vulnerability' } })).json();
			await expect.poll(async () => (await (await request.get(`/api/admin/jobs/${job.id}`)).json()).status, { timeout: 240_000, intervals: [2000] }).toBe('succeeded');
			const a = (await (await request.get(`/api/projects/${slug}/assessment`)).json()).report;
			expect(a.town.coastal).toBe(true);
			expect(a.scenarios.filter((s: { present: boolean }) => s.present).length).toBeGreaterThanOrEqual(4);
			const bld = a.exposure.find((e: { asset: string }) => e.asset === 'Buildings');
			expect(bld.total).toBeGreaterThan(500);
			// Sea level exposure grows with the scenario.
			expect(bld.by.slr_8_8.direct).toBeGreaterThanOrEqual(bld.by.slr_3_9.direct);
			expect(bld.by.slr_3_9.direct).toBeGreaterThanOrEqual(bld.by.slr_1_6.direct);
			expect(a.actions.length).toBeGreaterThan(2);
			await page.goto(`/p/${slug}/assessment`);
			await expect(page.getByRole('heading', { name: 'Castine town: vulnerability assessment' })).toBeVisible();
			for (const h of ['1. Community goals', '2. Hazards, impacts and planning horizons', '3. Vulnerability of valued community assets',
				'4. Relative risk of priority assets', '5. At-risk populations', '6. Recommendations', 'Methods and sources']) {
				await expect(page.getByRole('heading', { name: h })).toBeVisible();
			}
			await page.waitForFunction(() => window.__report?.ready === true, undefined, { timeout: 60_000 });
			await shot(page, 'assessment-castine');
		} finally {
			await request.delete(`/api/admin/projects/${slug}`);
		}
	});

	test('settlement editor: a "remove" edit drops a Maine hamlet, shows in the editor, and deleting it restores it', async ({ page, request }) => {
		const before = (await (await request.get('/api/admin/settlement-edits')).json()).stats;
		// Refused: outside Maine, and not a polygon.
		const square = (x: number, y: number, d: number) => ({
			type: 'Polygon',
			coordinates: [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]
		});
		const bad = await request.post('/api/admin/settlement-edits', { data: { type: 'Feature', geometry: square(-100, 40, 0.01), properties: { action: 'remove' } } });
		expect(bad.status()).toBe(422);
		expect((await bad.json()).detail).toContain('Maine');
		expect((await request.post('/api/admin/settlement-edits', { data: { type: 'Feature', geometry: { type: 'Point', coordinates: [-69, 45] }, properties: { action: 'remove' } } })).status()).toBe(422);

		// A computed hamlet, and a remove edit just around it.
		const items = await (await request.get('/tiles/collections/pub.maine_places__settlements/items?settlement_class=Hamlet&source=computed&limit=1&f=geojson')).json();
		const hamlet = items.features[0];
		const pts = (hamlet.geometry.coordinates as number[][][][]).flat(2);
		const [x, y] = [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length];
		// Inside the drawn square, no computed settlement is left afterwards (neighbours it cuts through count as edited pieces,
		// so the total can go either way).
		const inner = `${x - 0.002},${y - 0.002},${x + 0.002},${y + 0.002}`;
		const computedInside = async () =>
			(await (await request.get(`/tiles/collections/pub.maine_places__settlements/items?bbox=${inner}&source=computed&limit=50&f=geojson`)).json()).features.length;
		expect(await computedInside()).toBeGreaterThan(0);
		const created = await request.post('/api/admin/settlement-edits', {
			data: { type: 'Feature', geometry: square(x, y, 0.004), properties: { action: 'remove', note: 'e2e test: not a settlement' } }
		});
		expect(created.status()).toBe(201);
		const { edit, stats } = await created.json();
		try {
			expect(stats.edits.remove).toBe((before.edits.remove ?? 0) + 1);
			expect(await computedInside()).toBe(0);

			await page.goto('/admin/methods/settlements');
			await expect(page.getByRole('link', { name: 'Edit settlements' })).toHaveAttribute('href', '/admin/methods/settlements/edit');
			await page.goto('/admin/methods/settlements/edit');
			await expect(page.getByRole('heading', { name: 'Edit settlements' })).toBeVisible();
			await expect(page.getByRole('status').filter({ hasText: 'edited' })).toContainText(stats.settlements.toLocaleString('en-US'));
			await expect(page.getByLabel('Settlement edits')).toContainText('e2e test: not a settlement');
			await expect(page.getByRole('toolbar', { name: 'Draw an edit' }).getByRole('button')).toHaveCount(3);
			await shot(page, 'admin-settlement-editor');
		} finally {
			const del = await request.delete(`/api/admin/settlement-edits/${edit.id}`);
			expect(del.status()).toBe(200);
			expect((await del.json()).stats.settlements).toBe(before.settlements);
		}
	});

	test('parcel site: pick a parcel on the map, open its workspace, run agricultural potential, tracked on the methods page', async ({ page, request }) => {
		test.setTimeout(240_000);
		await page.goto('/admin/new?design=parcel-site');
		await expect(page.getByRole('radio', { name: /Parcel site/ })).toHaveAttribute('aria-checked', 'true');
		// Town first: the preview pane becomes a map of that town's parcels (and the address list is limited to it).
		await expect(page.getByText('Choose a town first: its parcels appear here.')).toBeVisible();
		await page.getByLabel('Town', { exact: true }).fill('Presque Isle');
		await page.getByRole('list', { name: 'Towns' }).getByRole('button', { name: /Presque Isle/ }).first().click();
		await expect(page.getByText('Town: Presque Isle')).toBeVisible();
		await page.getByLabel('Parcels in Presque Isle').fill('360 State');
		await expect(page.getByRole('list', { name: 'Places' }).getByRole('button', { name: /360 STATE ST/ })).toBeVisible();
		await page.getByLabel('Parcels in Presque Isle').fill('');
		await page.waitForFunction(() => !!(window as unknown as { __parcelPicker?: unknown }).__parcelPicker);
		// Only the town's parcels are drawn (tiles filtered to its GEOID): at the town line, every parcel is Presque Isle's.
		await page.evaluate(() => (window as unknown as { __parcelPicker: import('maplibre-gl').Map }).__parcelPicker.jumpTo({ center: [-68.06, 46.7], zoom: 14 }));
		const towns = async () =>
			page.evaluate(() => [
				...new Set(
					(window as unknown as { __parcelPicker: import('maplibre-gl').Map }).__parcelPicker
						.queryRenderedFeatures({ layers: ['parcels-fill'] })
						.map((f) => String(f.properties.name).split(', ').at(-1))
				)
			]);
		await expect.poll(towns, { timeout: 30_000 }).toEqual(['Presque Isle']);
		// Zoom to the parcel (360 State St) and click it.
		const at: [number, number] = [-67.993032, 46.68137];
		await page.evaluate((c) => (window as unknown as { __parcelPicker: import('maplibre-gl').Map }).__parcelPicker.jumpTo({ center: c, zoom: 16.5 }), at);
		await expect
			.poll(() => page.evaluate(() => (window as unknown as { __parcelPicker: import('maplibre-gl').Map }).__parcelPicker.queryRenderedFeatures({ layers: ['parcels-fill'] }).length), { timeout: 30_000 })
			.toBeGreaterThan(0);
		const xy = await page.evaluate((c) => (window as unknown as { __parcelPicker: import('maplibre-gl').Map }).__parcelPicker.project(c), at);
		const box = (await page.locator('.picker .maplibregl-canvas').boundingBox())!;
		await page.mouse.click(box.x + xy.x, box.y + xy.y);
		await expect(page.getByText('360 STATE ST, map/lot 012-187-360, Presque Isle')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Save project' })).toBeEnabled({ timeout: 30_000 });
		await shot(page, 'admin-parcel-1-picked');
		await page.getByRole('button', { name: 'Save project' }).click();
		// Saving a parcel project opens its workspace.
		await expect(page).toHaveURL(/\/admin\/projects\/360-state-st-parcel-site/);
		const slug = page.url().split('/').at(-1)!;
		try {
			const card = page.getByRole('article', { name: 'Agricultural potential' });
			await expect(card.getByRole('link', { name: 'How it works' })).toHaveAttribute('href', '/admin/methods/agricultural-potential');
			await card.getByRole('button', { name: 'Run' }).click();
			// When the new run finishes, its layer goes on the project's map (an earlier run of the same parcel may
			// already show as the latest result, so wait for the layer, not the result card).
			await expect
				.poll(async () => ((await (await request.get(`/api/projects/${slug}`)).json()).layers as { group?: string }[]).filter((l) => l.group === 'Analysis results').length, { timeout: 180_000 })
				.toBe(1);
			const result = card.getByLabel('Latest result');
			await expect(result).toContainText(/(High|Good|Moderate|Limited|Unsuitable) agricultural potential/);
			await expect(result.getByRole('table')).toContainText(/loam|silt|sand|muck|peat/i);
			await shot(page, 'admin-parcel-2-workspace');
			// A second analysis on the same parcel: wildfire fuel hazard (LANDFIRE fuel models), with its own report.
			const fire = page.getByRole('article', { name: 'Wildfire fuel hazard' });
			await expect(fire.getByRole('link', { name: 'How it works' })).toHaveAttribute('href', '/admin/methods/fire-risk');
			await fire.getByRole('button', { name: /^Run/ }).click();
			await expect
				.poll(async () => ((await (await request.get(`/api/projects/${slug}`)).json()).layers as { group?: string }[]).filter((l) => l.group === 'Analysis results').length, { timeout: 180_000 })
				.toBe(2);
			await expect(fire.getByLabel('Latest result')).toContainText(/(Very high|High|Moderate|Low|Very low) wildfire fuel hazard/);
			await expect(fire.getByLabel('Latest result').getByRole('table')).toContainText(/GR|GS|SH|TU|TL|NB/);

			// The analyses stay reachable from the map itself (admin, not the public site).
			await page.goto(`/p/${slug}`);
			await expect(page.getByRole('link', { name: 'Analyses' })).toHaveAttribute('href', `/admin/projects/${slug}`);
			// The methods page counts the run and links back to the workspace.
			await page.goto('/admin/methods/agricultural-potential');
			await expect(page.getByText('parcels analysed')).toBeVisible();
			await expect(page.getByRole('table').getByRole('link', { name: /360 STATE ST/ }).first()).toHaveAttribute('href', `/admin/projects/${slug}`);
			await expect(page.getByText('Code: workers/processes/py_agricultural_potential.py')).toBeVisible();
			await shot(page, 'admin-parcel-3-method');
		} finally {
			expect((await request.delete(`/api/admin/projects/${slug}`)).ok()).toBe(true);
		}
	});

	test('accessibility: no serious or critical axe violations', async ({ page }) => {
		for (const path of ['/admin', '/admin/datasets/me_boat_launches', '/admin/jobs', '/admin/new', '/admin/new/view', '/admin/analysis', '/admin/projects', '/admin/database', '/admin/data-api', '/admin/methods', '/admin/methods/settlements', '/admin/methods/agricultural-potential', '/admin/methods/fire-risk']) {
			await page.goto(path);
			if (path.includes('/datasets/')) await page.waitForFunction(() => window.__adminMap?.ready === true);
			const results = await new AxeBuilder({ page }).exclude('.maplibregl-canvas').analyze();
			const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
			expect(serious.map((v) => `${path}: ${v.id} (${v.nodes.length}): ${v.help}`)).toEqual([]);
		}
	});
});
