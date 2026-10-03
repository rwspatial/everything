// Reporter (plan: project-builder §1.6): prints a project's report page, /p/<slug>/report, to PDF with headless
// Chromium for `report` jobs on app.jobs. The page draws the same map and D3 charts as the site and sets
// window.__report.ready once the map snapshot and every chart are in. Output: data/reports/<slug>/<job>.pdf,
// recorded in app.reports. Claims with FOR UPDATE SKIP LOCKED, heartbeats, retries, and requeues jobs whose
// reporter died (no heartbeat for 3 minutes).
import { hostname } from 'node:os';
import { mkdir, rename, writeFile, utimes, open } from 'node:fs/promises';
import pg from 'pg';
import { chromium } from 'playwright-core';

const DB = process.env.WORKER_DATABASE_URL;
const SITE = process.env.SITE_URL ?? 'http://proxy';
const OUT = process.env.REPORTS_DIR ?? '/reports';
const ALIVE = '/tmp/reporter-alive';
const ID = `reporter@${hostname()}:${process.pid}`;
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const pool = new pg.Pool({ connectionString: DB, max: 3 });
let browser = null;
let stopping = false;
const log = (m) => console.log(`${new Date().toISOString()} ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function touch() {
	const now = new Date();
	try {
		await utimes(ALIVE, now, now);
	} catch {
		await (await open(ALIVE, 'w')).close();
	}
}

async function reap() {
	const { rows } = await pool.query(
		`UPDATE app.jobs SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END, locked_by = NULL,
		        finished_at = CASE WHEN attempts >= max_attempts THEN now() END,
		        error = CASE WHEN attempts >= max_attempts THEN jsonb_build_object('message', 'reporter stopped responding') ELSE error END
		  WHERE kind = 'report' AND status IN ('running', 'cancel_requested') AND heartbeat_at < now() - interval '3 minutes'
		  RETURNING id, status`
	);
	for (const r of rows) log(`reaper: job ${r.id} -> ${r.status}`);
}

async function claim() {
	const { rows } = await pool.query(
		`UPDATE app.jobs j SET status = 'running', locked_by = $1, locked_at = now(), heartbeat_at = now(), started_at = now(),
		        attempts = attempts + 1, progress = 0, progress_message = 'opening the report page', error = NULL
		  WHERE j.id = (SELECT id FROM app.jobs WHERE kind = 'report' AND status = 'queued' AND run_after <= now()
		                ORDER BY priority, id FOR UPDATE SKIP LOCKED LIMIT 1)
		  RETURNING j.*`,
		[ID]
	);
	return rows[0] ?? null;
}

const progress = (id, p, msg) =>
	pool.query(`UPDATE app.jobs SET progress = $2, progress_message = $3, heartbeat_at = now() WHERE id = $1`, [id, p, msg]);

async function render(job) {
	const slug = job.params?.slug;
	if (!SLUG.test(slug ?? '')) throw new Error(`invalid project slug ${JSON.stringify(slug)}`);
	browser ??= await chromium.launch();
	const context = await browser.newContext({ viewport: { width: 1000, height: 1300 }, deviceScaleFactor: 2 });
	const beat = setInterval(() => pool.query(`UPDATE app.jobs SET heartbeat_at = now() WHERE id = $1`, [job.id]).catch(() => {}), 15000);
	try {
		const page = await context.newPage();
		await page.goto(`${SITE}/p/${slug}/report`, { waitUntil: 'domcontentloaded', timeout: 60000 });
		await progress(job.id, 0.3, 'drawing the map and charts');
		await page.waitForFunction(() => window.__report?.ready === true || !!window.__report?.error, null, { timeout: 180000 });
		const err = await page.evaluate(() => window.__report?.error);
		if (err) throw new Error(`report page: ${err}`);
		await progress(job.id, 0.8, 'printing the PDF');
		const title = (await page.locator('h1').first().textContent())?.trim() ?? slug;
		const pdf = await page.pdf({
			format: 'Letter',
			printBackground: true,
			margin: { top: '0.5in', bottom: '0.65in', left: '0.55in', right: '0.55in' },
			displayHeaderFooter: true,
			headerTemplate: '<span></span>',
			footerTemplate: `<div style="font: 8px sans-serif; width: 100%; padding: 0 0.55in; color: #5b6670; display: flex; justify-content: space-between">
				<span>Downeast Geospatial · ${title.replace(/[<>&]/g, '')} · map report</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>`
		});
		const pages = (pdf.toString('latin1').match(/\/Type\s*\/Page(?![s\w])/g) ?? []).length || null;
		const rel = `${slug}/${job.id}.pdf`;
		await mkdir(`${OUT}/${slug}`, { recursive: true });
		await writeFile(`${OUT}/${rel}.part`, pdf);
		await rename(`${OUT}/${rel}.part`, `${OUT}/${rel}`);
		const client = await pool.connect();
		try {
			await client.query('BEGIN');
			const v = await client.query('SELECT version FROM app.projects WHERE slug = $1', [slug]);
			const r = await client.query(
				`INSERT INTO app.reports (slug, job_id, path, bytes, pages, manifest_version, created_by)
				 VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id`,
				[slug, job.id, rel, pdf.length, pages, v.rows[0]?.version ?? null, job.created_by]
			);
			const result = { report_id: r.rows[0].id, path: rel, url: `/api/projects/${slug}/reports/${r.rows[0].id}.pdf`, bytes: pdf.length, pages };
			await client.query(
				`UPDATE app.jobs SET status = 'succeeded', progress = 1, progress_message = 'done', result = $2, finished_at = now(), locked_by = NULL
				  WHERE id = $1`,
				[job.id, result]
			);
			await client.query('COMMIT');
			log(`job ${job.id}: ${slug} -> ${rel} (${pdf.length} bytes, ${pages} pages)`);
		} catch (e) {
			await client.query('ROLLBACK');
			throw e;
		} finally {
			client.release();
		}
	} finally {
		clearInterval(beat);
		await context.close();
	}
}

async function fail(job, e) {
	const retry = job.attempts < job.max_attempts;
	log(`job ${job.id}: ${retry ? 'will retry' : 'failed'}: ${e.message}`);
	await pool.query(
		`UPDATE app.jobs SET status = $2, locked_by = NULL, error = jsonb_build_object('message', $3::text),
		        run_after = now() + interval '30 seconds', finished_at = CASE WHEN $2 = 'failed' THEN now() END WHERE id = $1`,
		[job.id, retry ? 'queued' : 'failed', String(e.message).slice(0, 2000)]
	);
}

for (const s of ['SIGTERM', 'SIGINT']) process.on(s, () => (stopping = true));

log(`${ID} watching for report jobs (site ${SITE}, output ${OUT})`);
let lastReap = 0;
while (!stopping) {
	await touch();
	try {
		if (Date.now() - lastReap > 60000) {
			lastReap = Date.now();
			await reap();
		}
		const job = await claim();
		if (!job) {
			await sleep(3000);
			continue;
		}
		log(`job ${job.id}: report for ${job.params?.slug}`);
		try {
			await render(job);
		} catch (e) {
			await fail(job, e);
		}
	} catch (e) {
		log(`loop error: ${e.message}`);
		await sleep(5000);
	}
}
await browser?.close();
await pool.end();
log('stopped');
