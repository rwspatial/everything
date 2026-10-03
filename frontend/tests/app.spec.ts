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

test('landing page (identity, live selected work) and the About page (services, how it is built, contact)', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
	await expect(page).toHaveTitle(/Downeast Geospatial/);
	await expect(page.getByText('Bold Coast Geospatial')).toHaveCount(0); // the old studio name (the photo credit names the Bold Coast itself)
	await expect(page.getByRole('link', { name: /New England Wilderness Trust/ })).toBeVisible();
	const work = page.getByRole('list', { name: 'Selected work' });
	for (const name of ['Maine Coast', 'Maine Water', 'Maine Lands', 'Maine Infrastructure']) {
		await expect(work.getByRole('link', { name: new RegExp(`^${name}`) })).toBeVisible();
	}
	await expect(work.getByRole('link', { name: /World Overview/ })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'What I do' })).toHaveCount(0); // moved to /about
	await shot(page, '0-landing');
	await work.getByRole('link', { name: /^Maine Lands/ }).click();
	await expect(page).toHaveURL(/\/p\/maine-lands/);
	await page.getByRole('link', { name: '← All maps' }).click();
	await expect(page).toHaveURL(/\/maps$/);

	await page.goto('/');
	await page.getByRole('link', { name: 'About, services and contact →' }).click();
	await expect(page).toHaveURL(/\/about$/);
	await expect(page.getByRole('heading', { name: /^About / , level: 1 })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'What I do' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'How this site is built' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Work with me' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'rwspatial@gmail.com' })).toHaveAttribute('href', 'mailto:rwspatial@gmail.com');
	await expect(page.getByRole('link', { name: '(207) 266-1634' })).toHaveAttribute('href', 'tel:+12072661634');
	await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'About' })).toHaveAttribute('aria-current', 'page');
	await shot(page, '0b-about');
});

test('hub lists the placeholder projects with status and what is missing', async ({ page }) => {
	const api = page.waitForResponse((r) => r.url().endsWith('/api/projects') && r.status() === 200);
	await page.goto('/maps');
	await api; // the hub reads the project registry (core-api), not the static files
	const cards = page.getByRole('list', { name: 'Projects' });
	await expect(cards.getByRole('link', { name: 'World Overview', exact: true })).toBeVisible();
	await expect(cards.getByRole('link', { name: 'Hydrology Sketch', exact: true })).toBeVisible();
	await expect(cards.getByRole('link', { name: 'Analysis Sandbox', exact: true })).toBeVisible();
	for (const name of ['Maine Coast', 'Maine Water', 'Maine Lands', 'Maine Infrastructure', 'Maine Overview']) {
		await expect(cards.getByRole('link', { name, exact: true })).toBeVisible();
	}
	// Count drafts from the registry: projects saved in the /admin/new wizard also appear on the hub.
	const registry = await (await page.request.get('/api/projects')).json();
	const drafts = registry.projects.filter((p: { status: string }) => p.status === 'draft').length;
	await expect(page.getByText('Draft', { exact: true })).toHaveCount(drafts);
	await expect(page.getByText('Stub', { exact: true })).toHaveCount(2);
	const lands = cards.getByRole('listitem').filter({ has: page.getByRole('link', { name: 'Maine Lands', exact: true }) });
	await lands.getByText("What's missing?").click();
	await expect(lands.getByText(/trails/i).first()).toBeVisible();
	await shot(page, '1-hub');
});

test('hub and viewer fall back to the static manifests when core-api is unreachable', async ({ page }) => {
	await page.route('**/api/projects**', (route) => route.abort());
	await page.goto('/maps');
	await expect(page.getByRole('list', { name: 'Projects' }).getByRole('link', { name: 'Maine Overview', exact: true })).toBeVisible();
	await page.goto('/p/maine-overview');
	await mapIdle(page);
	expect(await rendered(page, 'towns')).toBeGreaterThan(400);
});

test('route badges on every map: interstate, US and state routes near Bangor', async ({ page }) => {
	await page.goto('/p/maine-lands?map=12/44.80/-68.78');
	await mapIdle(page);
	const kinds = await page.evaluate(() => {
		const m = window.__spatial!.map!;
		const fs = m.queryRenderedFeatures({ layers: ['o:route-shields-interstate', 'o:route-shields-us', 'o:route-shields-state'] });
		return [...new Set(fs.map((f) => `${f.properties.kind} ${f.properties.ref}`))];
	});
	expect(kinds).toEqual(expect.arrayContaining(['interstate 95', 'us 2', 'state 15']));
	await shot(page, '12-route-badges');
});

test('facility icons and settlement outlines: pictograms instead of dots, built-up areas in one colour', async ({ page }) => {
	await page.goto('/p/maine-facilities?map=12.5/43.665/-70.27');
	await mapIdle(page);
	expect(await rendered(page, 'schools')).toBeGreaterThan(0);
	expect(await page.evaluate(() => window.__spatial!.map!.hasImage('poi:school:9467bd'))).toBe(true);
	await shot(page, '13-facility-icons');
	await page.goto('/p/maine-places?map=10/43.75/-70.3');
	await mapIdle(page);
	expect(await rendered(page, 'settlements')).toBeGreaterThan(20);
	await shot(page, '14-settlements');
});

test('maine-overview (made with mapgen): towns shaded by ACS median household income', async ({ page }) => {
	await page.goto('/p/maine-overview');
	await mapIdle(page);
	expect(await rendered(page, 'towns')).toBeGreaterThan(400);
	await expect(page.getByText('Median household income (quintiles)')).toBeVisible();
	await expect(page.getByText('suppressed (very small places)')).toBeVisible();
	// Click Augusta (its TIGER interior point): the inspector shows the town and its income. (Hover popups are off.)
	const xy = await page.evaluate(() => window.__spatial!.map!.project([-69.7342, 44.3349]));
	const box = (await page.locator('.maplibregl-canvas').boundingBox())!;
	await page.mouse.move(box.x + xy.x, box.y + xy.y);
	await expect(page.locator('.hover-popup')).toHaveCount(0);
	await page.mouse.click(box.x + xy.x, box.y + xy.y);
	const details = page.getByRole('complementary', { name: 'Feature details' });
	await expect(details).toContainText('Augusta city');
	await expect(details.getByRole('row', { name: /median_hh_income/ }).first()).toContainText(/\d/);
	await shot(page, '7-maine-overview');
});

test('maine-terrain: elevation, hillshade and slope COGs; Katahdin elevation on click; contours when zoomed in', async ({ page }) => {
	const tiles: number[] = [];
	page.on('response', (r) => {
		if (/\/raster\/maine\/(dem|hillshade)_30m\/\d+\/\d+\/\d+\.png/.test(r.url())) tiles.push(r.status());
	});
	await page.goto('/p/maine-terrain');
	await mapIdle(page);
	expect(tiles.filter((s) => s === 200).length, 'elevation and hillshade tiles served').toBeGreaterThan(4);
	await expect(page.getByText('Elevation (m)')).toBeVisible();
	await shot(page, '10-maine-terrain');
	// Katahdin (1,606 m summit; a 30 m pixel reads a little lower). Zoom in so the click lands on the summit pixel.
	await page.evaluate(() => window.__spatial!.map!.jumpTo({ center: [-68.9213, 45.9044], zoom: 13 }));
	await mapIdle(page);
	const xy = await page.evaluate(() => window.__spatial!.map!.project([-68.9213, 45.9044]));
	await page.locator('.maplibregl-canvas').click({ position: { x: xy.x, y: xy.y } });
	const inspector = page.getByRole('complementary', { name: 'Feature details' });
	const value = parseFloat((await inspector.getByRole('region', { name: 'Elevation' }).getByRole('row', { name: /value/ }).locator('td').textContent())!);
	expect(value).toBeGreaterThan(1450);
	expect(value).toBeLessThan(1620);
	await expect.poll(() => rendered(page, 'contours')).toBeGreaterThan(10);
	await shot(page, '11-maine-terrain-katahdin');
});

test('maine-overview: county outlines over the town choropleth', async ({ page }) => {
	await page.goto('/p/maine-overview');
	await mapIdle(page);
	expect(await rendered(page, 'counties')).toBeGreaterThanOrEqual(16);
	await expect(page.getByRole('checkbox', { name: 'Median household income by census tract' })).not.toBeChecked();
	// ACS block groups (smallest ACS geography) and 2020 census blocks, over Portland.
	await page.getByRole('checkbox', { name: 'Median household income by block group' }).check();
	await page.getByRole('checkbox', { name: 'Population density by census block (2020)' }).check();
	await page.evaluate(() => window.__spatial!.map!.jumpTo({ center: [-70.27, 43.67], zoom: 12 }));
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'bg-income')).toBeGreaterThan(20);
	await expect.poll(() => rendered(page, 'blocks-density')).toBeGreaterThan(200);
	await shot(page, '16-maine-overview-blocks');
});

test('maine-places: Overture buildings and places over downtown Portland', async ({ page }) => {
	await page.goto('/p/maine-places?map=15.00/43.6570/-70.2560');
	await mapIdle(page);
	expect(await rendered(page, 'buildings')).toBeGreaterThan(100);
	expect(await rendered(page, 'places')).toBeGreaterThan(20);
	await shot(page, '12-maine-places');
});

test('main nav: Work, Maps, About & contact, Admin, then Data API at the far right', async ({ page }) => {
	await page.goto('/');
	const links = await page.getByRole('navigation', { name: 'Main' }).getByRole('link').allTextContents();
	expect(links.map((t) => t.trim())).toEqual(['Work', 'Maps', 'About & contact', 'Admin', 'Data API']);
	await page.goto('/tiles/');
	const api = await page.getByRole('navigation', { name: 'Main' }).getByRole('link').allTextContents();
	expect(api.map((t) => t.trim())).toEqual(['Work', 'Maps', 'About & contact', 'Admin', 'Data API']);
});

test('maine-energy and maine-facilities: EIA plants and grid, HIFLD facilities', async ({ page }) => {
	await page.goto('/p/maine-energy');
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'power-plants')).toBeGreaterThan(100);
	await expect.poll(() => rendered(page, 'transmission-lines')).toBeGreaterThan(50);
	await shot(page, '17-maine-energy');
	await page.goto('/p/maine-facilities');
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'hospitals')).toBeGreaterThan(30);
	await expect.poll(() => rendered(page, 'fire-ems')).toBeGreaterThan(300);
	await expect.poll(() => rendered(page, 'schools')).toBeGreaterThan(300);
	await shot(page, '18-maine-facilities');
});

test('maine-transportation: MaineDOT roads, bridges by condition, rail and airports around Augusta', async ({ page }) => {
	await page.goto('/p/maine-transportation');
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'public-roads')).toBeGreaterThan(500);
	await expect.poll(() => rendered(page, 'bridges')).toBeGreaterThan(50);
	await expect.poll(() => rendered(page, 'rail')).toBeGreaterThan(5);
	await shot(page, '19-maine-transportation');
});

test('maine-habitat: Beginning with Habitat blocks, focus areas and significant wildlife habitat', async ({ page }) => {
	await page.goto('/p/maine-habitat');
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'iwwh')).toBeGreaterThan(50);
	await expect.poll(() => rendered(page, 'iwwh')).toBeGreaterThan(50);
	await expect.poll(() => rendered(page, 'focus-areas')).toBeGreaterThan(3);
	await shot(page, '20-maine-habitat');
});

test('maine-broadband: share of locations without 100/20 Mbps by block group', async ({ page }) => {
	await page.goto('/p/maine-broadband');
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'bg-not-served')).toBeGreaterThan(300);
	await shot(page, '21-maine-broadband');
});

test('maine-soils: statewide hydrologic soil group grid, SSURGO map units from zoom 11', async ({ page }) => {
	const tiles: string[] = [];
	page.on('response', (r) => {
		if (r.status() === 200 && /\/raster\/maine\/soils_hsg_30m\/\d+\/\d+\/\d+\.png\?colormap=/.test(r.url())) tiles.push(r.url());
	});
	await page.goto('/p/maine-soils');
	await mapIdle(page);
	expect(tiles.length, 'categorical soil grid tiles served').toBeGreaterThan(4);
	await shot(page, '13-maine-soils');
	await page.evaluate(() => window.__spatial!.map!.jumpTo({ center: [-68.013, 46.68], zoom: 13 })); // Presque Isle
	await mapIdle(page);
	await expect.poll(() => rendered(page, 'hsg')).toBeGreaterThan(50);
	await shot(page, '14-maine-soils-presque-isle');
});

test('maine-landcover: LANDFIRE vegetation classes; a click names the ecological system', async ({ page }) => {
	await page.goto('/p/maine-landcover');
	await mapIdle(page);
	await expect(page.getByText('Mixed conifer-hardwood forest')).toBeVisible();
	await shot(page, '15-maine-landcover');
	await page.evaluate(() => window.__spatial!.map!.jumpTo({ center: [-69.5, 45.6], zoom: 13 }));
	await mapIdle(page);
	const xy = await page.evaluate(() => window.__spatial!.map!.project([-69.5, 45.6]));
	await page.locator('.maplibregl-canvas').click({ position: { x: xy.x, y: xy.y } });
	const inspector = page.getByRole('complementary', { name: 'Feature details' });
	// The class label from the manifest's categories, not the raw EVT code.
	await expect(inspector.getByRole('region', { name: 'Existing vegetation type' }).getByRole('row', { name: /value/ }).locator('td'))
		.toHaveText(/^[A-Z][A-Za-z -]+(Forest|Swamp|Woodland|Bog|Fen|Marsh|Shrubland)/);
});

test('world-overview draws countries and places from tiPG vector tiles', async ({ page }) => {
	await page.goto('/p/world-overview');
	await mapIdle(page);
	expect(await rendered(page, 'countries')).toBeGreaterThan(100);
	expect(await rendered(page, 'places')).toBeGreaterThan(50);
	expect(await rendered(page, 'admin1')).toBeGreaterThan(20);
	await expect(page.getByRole('checkbox', { name: 'States and provinces' })).toBeChecked();
	await shot(page, '2-world-overview');
});

test('layer toggle, opacity and feature inspector', async ({ page }) => {
	await page.goto('/p/world-overview');
	await mapIdle(page);

	await page.getByRole('checkbox', { name: 'Populated places' }).uncheck();
	await expect.poll(() => rendered(page, 'places')).toBe(0);
	await expect(page).toHaveURL(/v=countries,admin1(&|$)/);
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
	const country = drawer.getByRole('region', { name: 'Countries by population' });
	await expect(country.getByRole('cell', { name: 'Brazil', exact: true })).toBeVisible();
	// States and provinces sit on top of countries, so the Brazilian state under the click is listed too.
	await expect(drawer.getByRole('heading', { name: 'States and provinces' }).first()).toBeVisible();
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
	// Places now draws below States and provinces (URL "o" is top → bottom).
	await expect(page).toHaveURL(/[?&]o=/);
	const order = new URL(page.url()).searchParams.get('o')!.split(',');
	expect(order.indexOf('places')).toBeGreaterThan(order.indexOf('admin1'));
	await page.reload();
	await mapIdle(page);
	const titles = await page.locator('.tree .layer label[for]').allTextContents();
	expect(titles.indexOf('Populated places')).toBeGreaterThan(titles.indexOf('States and provinces'));
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

test('maine-lands: COG through titiler draws, and a click reads the pixel value', async ({ page }) => {
	const tiles: number[] = [];
	page.on('response', (r) => {
		if (/\/raster\/maine\/phzm_2023_min_temp\/\d+\/\d+\/\d+\.png/.test(r.url())) tiles.push(r.status());
	});
	await page.goto('/p/maine-lands');
	await mapIdle(page);
	expect(tiles.length, 'raster tiles requested').toBeGreaterThan(0);
	expect(tiles.filter((s) => s === 200).length, 'raster tiles served').toBeGreaterThan(0);
	await expect(page.getByText('Avg. annual extreme minimum (°F)')).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'Plant hardiness zones (2023)' })).not.toBeChecked();

	// Click inland Maine (Augusta area): the Inspector shows the titiler point value.
	const xy = await page.evaluate(() => window.__spatial!.map!.project([-69.78, 44.31]));
	await page.locator('.maplibregl-canvas').click({ position: { x: xy.x, y: xy.y } });
	const inspector = page.getByRole('complementary', { name: 'Feature details' });
	await expect(inspector.getByRole('heading', { name: 'Extreme minimum temperature (grid)' })).toBeVisible();
	const value = parseFloat((await inspector.getByRole('row', { name: /value/ }).locator('td').first().textContent())!);
	expect(value).toBeGreaterThan(-20);
	expect(value).toBeLessThan(-5);
	await shot(page, '6-maine-lands-cog');
});

test('analysis-sandbox (empty placeholder) opens cleanly', async ({ page }) => {
	await page.goto('/p/analysis-sandbox');
	await mapIdle(page);
	await expect(page.getByText('Phase 5: job results will appear here as layers.')).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'Hot spots (vector)' })).toBeDisabled();
	await shot(page, '5-analysis-sandbox');
});

test('Data API pages (tiPG at /tiles/) carry the site bar, banner and footer, and the site links to them', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Data API' }).click();
	await expect(page).toHaveURL(/\/tiles\/$/);
	await expect(page).toHaveTitle(/Data API · Downeast Geospatial/);
	await expect(page.getByRole('heading', { name: 'Downeast Geospatial Data API', level: 1 })).toBeVisible(); // tiPG's page title
	await expect(page.getByRole('region', { name: 'Data API' })).toContainText('served live from PostGIS'); // the banner
	await expect(page.getByRole('link', { name: /Downeast Geospatial/ }).first()).toHaveAttribute('href', '/');
	await expect(page.getByRole('link', { name: /New England Wilderness Trust/ })).toBeVisible();
	await shot(page, '8-data-api');
	await page.goto('/tiles/collections/pub.maine_overview__towns/tiles/WebMercatorQuad/map.html');
	await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Maps' })).toBeVisible();
	await shot(page, '9-data-api-map');
});

test('unknown project shows a helpful 404', async ({ page }) => {
	await page.goto('/p/does-not-exist');
	await expect(page.getByRole('heading', { name: 'Not found' })).toBeVisible();
	await expect(page.getByRole('link', { name: '← All maps' })).toBeVisible();
});

test('accessibility: no serious or critical axe violations', async ({ page }) => {
	for (const path of ['/', '/about', '/maps', '/new', '/p/world-overview', '/p/maine-overview']) {
		await page.goto(path);
		if (path.startsWith('/p/')) await mapIdle(page);
		const results = await new AxeBuilder({ page }).exclude('.maplibregl-canvas').analyze();
		const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
		expect(serious.map((v) => `${path}: ${v.id} (${v.nodes.length}): ${v.help}`)).toEqual([]);
	}
});
