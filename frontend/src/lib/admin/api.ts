// Client for /api/admin/* (core-api). The browser already holds the Basic credentials from the
// /admin page load, so same-origin requests are authenticated automatically.

export type Health = 'ok' | 'warn' | 'fail' | 'unknown';
export type BBox = [number, number, number, number];

export interface RunRef {
	id: number;
	status: string;
	action: string;
	triggered_by: string;
	started_at: string | null;
	finished_at: string | null;
}

export interface DatasetRow {
	name: string;
	title: string;
	description: string | null;
	agency: string | null;
	kind: string;
	group_name: string | null;
	enabled: boolean;
	license: string | null;
	attribution: string | null;
	vintage: { label?: string; year?: number | string; period?: string };
	coverage: { extent?: string };
	requires_keys: string[];
	orphaned: boolean;
	sync_error: string | null;
	extent_name: string | null;
	received_ratio: number | null;
	bbox: BBox | null;
	outputs_total: number;
	health_ok: number;
	health_warn: number;
	health_fail: number;
	rows: number | null;
	bytes: number | null;
	projects: string[] | null;
	freshness: 'current' | 'stale' | 'unknown' | 'error' | null;
	freshness_checked_at: string | null;
	parts_total: number;
	parts_current: number;
	last_run: RunRef | null;
	status: 'ok' | 'failed' | 'unhealthy' | 'stale' | 'disabled' | 'unknown';
}

export interface RasterFacts {
	width: number;
	height: number;
	bands: number;
	dtype: string;
	crs: string | null;
	resolution: [number, number];
	nodata: number | null;
	min: number | null;
	max: number | null;
}

export interface Output {
	id: number;
	kind: string;
	locator: string;
	public_url: string | null;
	projects: string[];
	source: string | null;
	source_srs: string | null;
	target_srs: string | null;
	geometry_type: string | null;
	srid: number | null;
	row_count: number | null;
	invalid_geom_count: number | null;
	/** COG facts recorded at build time (kind 'cog'). */
	raster: RasterFacts | null;
	bytes: number | null;
	checksum: string | null;
	loaded_run_id: number | null;
	imported_at: string | null;
	imported_by: string | null;
	notes: string | null;
	health: Health;
	health_detail: string | null;
	health_checked_at: string | null;
	bbox: BBox | null;
}

export interface Part {
	part_key: string;
	part_kind: string | null;
	upstream_version: string | null;
	upstream_etag: string | null;
	upstream_last_modified: string | null;
	upstream_bytes: number | null;
	loaded_version: string | null;
	loaded_date: string | null;
	loaded_run_id: number | null;
	checksum: string | null;
	bytes: number | null;
	row_count: number | null;
	status: string;
	status_detail: string | null;
	checked_at: string | null;
}

export interface RunSummary {
	id: number;
	recipe_name?: string | null;
	action: string;
	status: string;
	outcome: string | null;
	triggered_by: string;
	started_at: string | null;
	finished_at: string | null;
	seconds: number | null;
	rows_written: number | null;
	bytes_downloaded: number | null;
	error?: string | null;
}

export interface DatasetDetail extends DatasetRow {
	upstream: { url?: string; path?: string };
	declared_outputs: unknown[];
	freshness_spec: { method?: string; every?: string };
	todo: string | null;
	yaml_path: string | null;
	yaml_text: string | null;
	yaml_sha256: string | null;
	outputs: Output[];
	parts: Part[];
	freshness_checks: { method: string; verdict: string; detail: string | null; observed: Record<string, unknown>; checked_at: string }[];
	keys: { key_name: string; configured: boolean; fingerprint: string | null; reported_at: string }[];
	runs: RunSummary[];
	active_jobs: ActiveJob[];
}

export interface ActiveJob {
	id: number;
	action: string;
	status: string;
	progress_message: string | null;
	attempts: number;
	max_attempts: number;
	run_after: string;
	created_by: string;
	created_at: string;
}

/** A queued job as returned by GET /api/admin/jobs/{id}. */
export interface JobDetail extends ActiveJob {
	kind: string;
	recipe_name: string | null;
	result: { plan?: Record<string, unknown> } | null;
	error: { message: string; log_tail?: string } | null;
	run_id: number | null;
	finished_at: string | null;
	deduplicated?: boolean;
}

export const ACTIVE_STATES = ['queued', 'running', 'cancel_requested'];

/** POST to /api/admin/*; throws AdminApiError with the server's message. */
export async function post<T>(fetchFn: typeof fetch, path: string, body: unknown = {}): Promise<T> {
	const res = await fetchFn(`/api/admin${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
		body: JSON.stringify(body)
	});
	const data = await res.json().catch(() => ({}));
	if (!res.ok) throw new AdminApiError(res.status, typeof data.detail === 'string' ? data.detail : `${res.status} ${res.statusText}`);
	return data as T;
}

export interface RunDetail extends RunSummary {
	job_id: number | null;
	params: Record<string, unknown>;
	host: string | null;
	log_tail: string | null;
	error: string | null;
	report: Record<string, unknown>;
	job_status: string | null;
	job_created_by: string | null;
}

export interface Job {
	id: number;
	recipe_name: string | null;
	action: string;
	status: string;
	concurrency_class: string;
	attempts: number;
	max_attempts: number;
	locked_by: string | null;
	created_by: string;
	created_at: string;
	heartbeat_at: string | null;
	finished_at: string | null;
	run_id: number | null;
	kind?: string;
	progress_message?: string | null;
}

export class AdminApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

export async function api<T>(fetchFn: typeof fetch, path: string): Promise<T> {
	const res = await fetchFn(`/api/admin${path}`, { headers: { Accept: 'application/json' }, cache: 'no-store' });
	if (!res.ok) {
		throw new AdminApiError(
			res.status,
			res.status === 401 ? 'Not signed in. Reload the page to log in.' : `${res.status} ${res.statusText} for ${path}`
		);
	}
	return res.json() as Promise<T>;
}

// ---- database health (/api/admin/database) ---------------------------------------------------------

export interface DbIssue {
	level: 'fail' | 'warn';
	code: string;
	message: string;
}

export interface DbView {
	name: string;
	geom: string;
	geometry_type: string | null;
	analysis_output: boolean;
	sources: string[];
	spatial_index_usable: boolean | null;
	error: string | null;
}

export interface DbTable {
	schema: string;
	name: string;
	rows: number;
	bytes: number;
	geom: string | null;
	geometry_type: string | null;
	dims: number | null;
	spatial_index: boolean;
	indexes: number;
	seq_scan: number | null;
	seq_tup_read: number | null;
	idx_scan: number | null;
	n_live_tup: number | null;
	n_dead_tup: number | null;
	last_analyzed: string | null;
	last_vacuumed: string | null;
	issues: DbIssue[];
}

export interface DatabaseHealth {
	db_bytes: number;
	stats_since: string | null;
	checked_at: string;
	summary: { views: number; views_indexed: number; tables: number; tables_with_issues: number; unused_index_bytes: number };
	views: DbView[];
	tables: DbTable[];
	unused_indexes: { index: string; table: string; bytes: number; method: string }[];
}

// ---- formatting -----------------------------------------------------------------------------

const nf = new Intl.NumberFormat();

export const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? '–' : nf.format(n));

export function fmtBytes(n: number | null | undefined): string {
	if (n === null || n === undefined) return '–';
	const units = ['B', 'KB', 'MB', 'GB', 'TB'];
	let i = 0;
	let v = n;
	while (v >= 1024 && i < units.length - 1) {
		v /= 1024;
		i++;
	}
	return `${v < 10 && i ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

export function fmtDate(s: string | null | undefined): string {
	if (!s) return '–';
	return new Date(s).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function fmtAgo(s: string | null | undefined): string {
	if (!s) return '–';
	const sec = Math.round((Date.now() - new Date(s).getTime()) / 1000);
	if (sec < 60) return 'just now';
	const units: [number, string][] = [
		[60, 'min'],
		[3600, 'h'],
		[86400, 'd']
	];
	let label = `${Math.round(sec / 60)} min`;
	for (const [size, name] of units) if (sec >= size) label = `${Math.round(sec / size)} ${name}`;
	return `${label} ago`;
}

export function fmtDuration(value: number | string | null | undefined): string {
	if (value === null || value === undefined || value === '') return '–';
	const seconds = Number(value);
	if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
	if (seconds < 90) return `${seconds.toFixed(1)} s`;
	return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export const fmtBBox = (b: BBox | null) => (b ? b.map((v) => Number(v).toFixed(2)).join(', ') : '–');

// /api/admin/methods: how derived layers are calculated (docs/methods/<id>.json). `math` is LaTeX (KaTeX).
export interface MethodSummary {
	id: string;
	title: string;
	summary: string;
	project: string | null;
	layer: string | null;
}

export interface Method extends MethodSummary {
	sql: string | null;
	sql_text?: string;
	outputs: { collection: string; sums?: string[] }[];
	inputs: { name: string; role: string }[];
	steps: { title: string; detail: string; math?: string }[];
	parameters: { name: string; value: string; why: string; math?: string }[];
	caveats: string[];
	live: { collection: string; rows?: number; sums?: Record<string, number | null>; error?: string }[];
}
