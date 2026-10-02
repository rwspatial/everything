// Generate src/lib/contracts.gen.ts from contracts/project-manifest.v1.schema.json.
//   node scripts/contracts.mjs          write the file    (make contracts)
//   node scripts/contracts.mjs check    fail if it is stale (make contracts-check, run by make verify)
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { compileFromFile } from 'json-schema-to-typescript';

const SCHEMA = `${process.env.CONTRACTS_DIR ?? '/contracts'}/project-manifest.v1.schema.json`;
const OUT = 'src/lib/contracts.gen.ts';

const banner = `// GENERATED from contracts/project-manifest.v1.schema.json by scripts/contracts.mjs. Do not edit:
// change the schema, then run \`make contracts\`.
import type { DistributiveOmit, LayerSpecification } from 'maplibre-gl';

/** A MapLibre layer minus id/source/source-layer, which the adapter injects. */
export type MapLibreStyleFragment = DistributiveOmit<LayerSpecification, 'id' | 'source' | 'source-layer'>;`;

const ts = await compileFromFile(SCHEMA, {
	bannerComment: banner,
	additionalProperties: false,
	unreachableDefinitions: true,
	style: { useTabs: true, singleQuote: true, printWidth: 120, trailingComma: 'none' }
});

if (process.argv[2] === 'check') {
	const current = existsSync(OUT) ? readFileSync(OUT, 'utf8') : '';
	if (current !== ts) {
		console.error(`FAIL  ${OUT} is out of date with the schema: run make contracts`);
		process.exit(1);
	}
	console.log(`PASS  ${OUT} matches contracts/project-manifest.v1.schema.json`);
} else {
	writeFileSync(OUT, ts);
	console.log(`wrote ${OUT}`);
}
