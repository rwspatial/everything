// Validate every layer's MapLibre style fragments with the official style-spec validator.
//   node scripts/validate-styles.mjs [slug ...]     (default: every project in /projects)
// Prints one JSON object per error {slug, path, code, message}; exits 1 if any fragment is invalid.
// The adapter injects id/source/source-layer, so each fragment is checked inside a minimal style
// with a source of the right kind (vector tiles, GeoJSON or raster) for its layer.
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { validateStyleMin } from '@maplibre/maplibre-gl-style-spec';

const ROOT = process.env.PROJECTS_DIR ?? '/projects';
const slugs = process.argv.slice(2).length
	? process.argv.slice(2)
	: readdirSync(ROOT).filter((d) => existsSync(`${ROOT}/${d}/project.json`)).sort();

function sourceFor(type) {
	switch (type) {
		case 'tipg-vector':
			return { src: { type: 'vector', tiles: ['http://x/{z}/{x}/{y}'] }, sourceLayer: 'default' };
		case 'geojson-url':
			return { src: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } } };
		default:
			return { src: { type: 'raster', tiles: ['http://x/{z}/{x}/{y}.png'], tileSize: 256 } };
	}
}

let failed = 0;
let checked = 0;
for (const slug of slugs) {
	const manifest = JSON.parse(readFileSync(`${ROOT}/${slug}/project.json`, 'utf8'));
	manifest.layers.forEach((layer, i) => {
		if (layer.status === 'todo' || !layer.style) return;
		const { src, sourceLayer } = sourceFor(layer.source.type);
		layer.style.layers.forEach((fragment, j) => {
			const id = `${layer.id}-${j}`;
			const style = {
				version: 8,
				sources: { s: src },
				layers: [{ ...fragment, id, source: 's', ...(sourceLayer ? { 'source-layer': sourceLayer } : {}) }]
			};
			checked++;
			for (const e of validateStyleMin(style)) {
				failed++;
				const message = e.message.replace(/^layers\[0\]\.?/, '').replace(/^: /, '');
				console.log(JSON.stringify({ slug, path: `layers[${i}].style.layers[${j}]`, code: 'E_STYLE', message }));
			}
		});
	});
}
console.error(`${failed ? 'FAIL' : 'PASS'}  MapLibre style spec: ${checked} fragments in ${slugs.length} project(s), ${failed} error(s)`);
process.exit(failed ? 1 : 0);
