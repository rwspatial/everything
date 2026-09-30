import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const shot = (page: Page, name: string) => page.screenshot({ path: `test-results/screens/${name}.png` });

/** Wait until the viewer added its layers and MapLibre finished loading tiles. */
async function mapIdle(page: Page) {
	await page.waitForFunction(() => window.__spatial?.ready === true, undefined, { timeout: 30_000 });
	await page.waitForFunction(() => window.__spatial?.idle === true, undefined, { timeout: 30_000 });
}

const rendered = (page: Page, layerId: string) => page.evaluate((id) => window.__spatial!.renderedCount(id), layerId);

let pageErrors: string[] = [];
test.beforeEach(({ page }) => {
	pageErrors = [];
	page.on('pageerror', (e) => pageErrors.push(e.message));
});
test.afterEach(() => {
	expect(pageErrors, 'uncaught errors in the page').toEqual([]);
});

test('hub lists the placeholder projects with status and what is missing', async ({ page }) => {
	await page.goto('/');
	const cards = page.getByRole('list', { name: 'Projects' });
	await expect(cards.getByRole('link', { name: 'World Overview', exact: true })).toBeVisible();
	await expect(cards.getByRole('link', { name: 'Hydrology Sketch', exact: true })).toBeVisible();
	await expect(cards.getByRole('link', { name: 'Analysis Sandbox', exact: true })).toBeVisible();
	await expect(page.getByText('Draft', { exact: true })).toHaveCount(1);
	await expect(page.getByText('Stub', { exact: true })).toHaveCount(2);
	await expect(page.getByText('2 of 5 pending')).toBeVisible();
	await page.getByText("What's missing?").first().click();
	await expect(page.getByText(/ne_admin1/).first()).toBeVisible();
	await shot(page, '1-hub');
});

test('world-overview draws countries and places from tiPG vector tiles', async ({ page }) => {
	await page.goto('/p/world-overview');
	await mapIdle(page);
	expect(await rendered(page, 'countries')).toBeGreaterThan(100);
	expect(await rendered(page, 'places')).toBeGreaterThan(50);
	await expect(page.getByText('States and provinces')).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'States and provinces' })).toBeDisabled();
	await shot(page, '2-world-overview');
});

test('layer toggle, opacity and feature inspector', async ({ page }) => {
	await page.goto('/p/world-overview');
	await mapIdle(page);

	await page.getByRole('checkbox', { name: 'Populated places' }).uncheck();
	await expect.poll(() => rendered(page, 'places')).toBe(0);
	await expect(page).toHaveURL(/v=countries(&|$)/);
	await page.getByRole('checkbox', { name: 'Populated places' }).check();
	await expect.poll(() => rendered(page, 'places')).toBeGreaterThan(50);

	await page.getByRole('slider', { name: 'Countries by population opacity' }).fill('0.4');
	await expect(page.getByText('40%')).toBeVisible();

	// Click Brazil and inspect its attributes.
	const pt = await page.evaluate(() => window.__spatial!.map!.project([-52, -10]));
	const box = (await page.locator('.maplibregl-canvas').boundingBox())!;
	await page.mouse.click(box.x + pt.x, box.y + pt.y);
	const drawer = page.getByRole('complementary', { name: 'Feature details' });
	await expect(drawer).toBeVisible();
	await expect(drawer.getByRole('cell', { name: 'Brazil' })).toBeVisible();
	await shot(page, '3-inspector');
	await page.keyboard.press('Escape');
	await expect(drawer).toBeHidden();
});

test('switching basemap keeps project layers drawn (and offline basemap works)', async ({ page }) => {
	await page.goto('/p/world-overview');
	await mapIdle(page);
	await page.getByRole('combobox', { name: 'Basemap' }).selectOption('none');
	await expect(page).toHaveURL(/[?&]b=none/);
	await mapIdle(page);
	expect(await rendered(page, 'countries')).toBeGreaterThan(100);
	expect(await rendered(page, 'places')).toBeGreaterThan(50);
	// Project layers sit below basemap labels when the basemap has any.
	await page.getByRole('combobox', { name: 'Basemap' }).selectOption('positron');
	await mapIdle(page);
	const order = await page.evaluate(() => window.__spatial!.map!.getStyle().layers.map((l) => `${l.type}:${l.id}`));
	const firstLabel = order.findIndex((x) => x.startsWith('symbol:') && !x.includes(':p:'));
	const lastOurs = order.findLastIndex((x) => x.includes(':p:'));
	expect(lastOurs).toBeLessThan(firstLabel);
	expect(await rendered(page, 'countries')).toBeGreaterThan(100);
});

test('aerial basemap: imagery loads, data stays on top, labels above data', async ({ page }) => {
	await page.goto('/p/world-overview');
	await mapIdle(page);
	await page.getByRole('combobox', { name: 'Basemap' }).selectOption('aerial-labels');
	await expect(page).toHaveURL(/[?&]b=aerial-labels/);
	await mapIdle(page);
	const state = await page.evaluate(() => {
		const map = window.__spatial!.map!;
		const ids = map.getStyle().layers.map((l) => l.id);
		return { ids, imageryLoaded: map.isSourceLoaded('imagery') };
	});
	expect(state.imageryLoaded).toBe(true);
	expect(state.ids.indexOf('imagery')).toBeLessThan(state.ids.indexOf('p:countries:0'));
	expect(state.ids.indexOf('p:places:0')).toBeLessThan(state.ids.indexOf('labels'));
	expect(await rendered(page, 'countries')).toBeGreaterThan(100);
	await page.getByRole('slider', { name: 'Countries by population opacity' }).fill('0.35');
	await mapIdle(page);
	await shot(page, '7-aerial');
	// Survives a reload (basemap is part of the shareable URL).
	await page.reload();
	await mapIdle(page);
	await expect(page.getByRole('combobox', { name: 'Basemap' })).toHaveValue('aerial-labels');
});

test('layer order can be changed and is kept in the URL', async ({ page }) => {
	await page.goto('/p/world-overview');
	await mapIdle(page);
	await page.getByRole('button', { name: 'Move Populated places down' }).click();
	// Skips the undrawn to-do layer (admin1): Places now draws below Countries (URL "o" is top → bottom).
	await expect(page).toHaveURL(/[?&]o=/);
	const order = new URL(page.url()).searchParams.get('o')!.split(',');
	expect(order.indexOf('places')).toBeGreaterThan(order.indexOf('countries'));
	await page.reload();
	await mapIdle(page);
	const titles = await page.locator('.tree .layer label[for]').allTextContents();
	expect(titles.indexOf('Populated places')).toBeGreaterThan(titles.indexOf('Countries by population'));
});

test('hydrology-sketch: GeoJSON lakes and the parametrized PostGIS function layer', async ({ page }) => {
	await page.goto('/p/hydrology-sketch');
	await mapIdle(page);
	expect(await rendered(page, 'lakes')).toBeGreaterThan(10);
	const before = await rendered(page, 'rivers-by-rank');
	expect(before).toBeGreaterThan(0);

	const slider = page.getByRole('slider', { name: 'Rivers by rank (PostGIS function): Max rank' });
	await slider.fill('1');
	await slider.dispatchEvent('change');
	await expect(page).toHaveURL(/pa\.rivers-by-rank\.max_scalerank=1/);
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'rivers-by-rank')).toBeLessThan(before);
	await shot(page, '4-hydrology');
});

test('analysis-sandbox (empty placeholder) opens cleanly', async ({ page }) => {
	await page.goto('/p/analysis-sandbox');
	await mapIdle(page);
	await expect(page.getByText('Phase 5: job results will appear here as layers.')).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'Hot spots (vector)' })).toBeDisabled();
	await shot(page, '5-analysis-sandbox');
});

test('unknown project shows a helpful 404', async ({ page }) => {
	await page.goto('/p/does-not-exist');
	await expect(page.getByRole('heading', { name: 'Not found' })).toBeVisible();
	await expect(page.getByRole('link', { name: '← Back to projects' })).toBeVisible();
});

test('accessibility: no serious or critical axe violations', async ({ page }) => {
	for (const path of ['/', '/new', '/p/world-overview']) {
		await page.goto(path);
		if (path.startsWith('/p/')) await mapIdle(page);
		const results = await new AxeBuilder({ page }).exclude('.maplibregl-canvas').analyze();
		const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
		expect(serious.map((v) => `${path}: ${v.id} (${v.nodes.length}): ${v.help}`)).toEqual([]);
	}
});
