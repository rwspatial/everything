// GENERATED from contracts/project-manifest.v1.schema.json by scripts/contracts.mjs. Do not edit:
// change the schema, then run `make contracts`.
import type {DistributiveOmit, LayerSpecification} from 'maplibre-gl';

/** A MapLibre layer minus id/source/source-layer, which the adapter injects. */
export type MapLibreStyleFragment = DistributiveOmit<LayerSpecification, 'id' | 'source' | 'source-layer'>;

/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "ProjectStatus".
 */
export type ProjectStatus = 'stub' | 'draft' | 'ready';
/**
 * @minItems 2
 * @maxItems 2
 *
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "LngLat".
 */
export type LngLat = [number, number];
/**
 * @minItems 4
 * @maxItems 4
 *
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "BBox".
 */
export type BBox = [number, number, number, number];
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "LayerStatus".
 */
export type LayerStatus = 'ready' | 'todo';
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "SourceSpec".
 */
export type SourceSpec = TipgVectorSource | TipgGeojsonSource | GeojsonUrlSource | RasterXyzSource | RasterCogSource;
/**
 * A tiPG collection id: a view or function in the pub schema.
 *
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "Collection".
 */
export type Collection = string;
/**
 * A MapLibre style layer minus id/source/source-layer, which the adapter injects. Checked in full by the MapLibre style-spec validator (make validate).
 *
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "StyleFragment".
 */
export type StyleFragment = MapLibreStyleFragment;
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "LegendSpec".
 */
export type LegendSpec = CategoricalLegend | GradientLegend | SingleLegend | NoLegend;
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "ChartFormat".
 */
export type ChartFormat = 'number' | 'count' | 'currency' | 'percent' | 'acres' | 'sqmi' | 'years' | 'mw';
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "ChartAgg".
 */
export type ChartAgg = 'count' | 'sum' | 'avg' | 'median' | 'min' | 'max';

/**
 * One map project (plan §2.1). Source of truth for the TypeScript types (frontend/src/lib/contracts.gen.ts) and for validation in mapgen and core-api (contracts/validate.py).
 */
export interface ProjectManifest {
	manifestVersion: 1;
	slug: string;
	title: string;
	status: ProjectStatus;
	description?: string;
	tags?: string[];
	view: ViewSpec;
	layers: LayerSpec[];
	/**
	 * Free-text to-do notes for placeholder projects, shown on the hub and in the viewer.
	 */
	notes?: string[];
	/**
	 * D3 charts computed on the fly from the project's published data (GET /api/projects/{slug}/charts/{id}), shown in the viewer's Charts panel and in PDF reports.
	 */
	charts?: ChartSpec[];
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "ViewSpec".
 */
export interface ViewSpec {
	center: LngLat;
	zoom: number;
	bounds?: BBox | null;
	basemap?: string;
}
/**
 * One visual layer. `source.type` selects the frontend adapter (src/lib/adapters.ts).
 *
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "LayerSpec".
 */
export interface LayerSpec {
	id: string;
	title: string;
	group?: string;
	status?: LayerStatus;
	todo?: string | null;
	visible?: boolean;
	opacity?: number;
	minzoom?: number;
	maxzoom?: number;
	source: SourceSpec;
	style?: StyleSpec;
	legend?: LegendSpec;
	interaction?: InteractionSpec;
	/**
	 * UI controls bound to tiPG function arguments (source.params).
	 */
	controls?: ParamControl[];
	attribution?: string;
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "TipgVectorSource".
 */
export interface TipgVectorSource {
	type: 'tipg-vector';
	collection: Collection;
	tms?: string;
	params?: FunctionParams;
	properties?: string[];
	maxzoom?: number;
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "FunctionParams".
 */
export interface FunctionParams {
	[k: string]: string | number;
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "TipgGeojsonSource".
 */
export interface TipgGeojsonSource {
	type: 'tipg-geojson';
	collection: Collection;
	params?: FunctionParams;
	properties?: string[];
	limit?: number;
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "GeojsonUrlSource".
 */
export interface GeojsonUrlSource {
	type: 'geojson-url';
	url: string;
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "RasterXyzSource".
 */
export interface RasterXyzSource {
	type: 'raster-xyz';
	/**
	 * @minItems 1
	 */
	tiles: [string, ...string[]];
	tileSize?: 256 | 512;
	maxzoom?: number;
}
/**
 * A COG in data/cog/, served by titiler through the proxy's /raster/<cog>/... route.
 *
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "RasterCogSource".
 */
export interface RasterCogSource {
	type: 'raster-cog';
	cog: string;
	/**
	 * @minItems 2
	 * @maxItems 2
	 */
	rescale?: [number, number];
	colormap?: string;
	/**
	 * Classes of a categorical raster (soil groups, vegetation types): each pixel value gets its own colour, values not listed are transparent, and a click shows the label. Use instead of rescale/colormap.
	 *
	 * @minItems 1
	 * @maxItems 400
	 */
	categories?: [
		{
			value: number;
			color: string;
			label?: string;
		},
		...{
			value: number;
			color: string;
			label?: string;
		}[]
	];
	bidx?: number;
	maxzoom?: number;
	/**
	 * Unit label for the pixel value shown when the map is clicked (titiler point query).
	 */
	units?: string;
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "StyleSpec".
 */
export interface StyleSpec {
	kind: 'maplibre';
	layers: StyleFragment[];
}
export interface CategoricalLegend {
	type: 'categorical';
	title?: string;
	items: {
		label: string;
		color: string;
	}[];
}
export interface GradientLegend {
	type: 'gradient';
	title?: string;
	/**
	 * @minItems 2
	 */
	stops: [
		{
			value: string;
			color: string;
		},
		{
			value: string;
			color: string;
		},
		...{
			value: string;
			color: string;
		}[]
	];
}
export interface SingleLegend {
	type: 'single';
	label?: string;
	color: string;
}
export interface NoLegend {
	type: 'none';
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "InteractionSpec".
 */
export interface InteractionSpec {
	popup?: {
		template: string;
	};
	inspect?: boolean;
}
/**
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "ParamControl".
 */
export interface ParamControl {
	param: string;
	label: string;
	type: 'range';
	min: number;
	max: number;
	step?: number;
}
/**
 * One chart: an aggregate of a pub view computed by core-api (never free SQL). bar/donut: `category` with `agg` of `value` (count needs no value); histogram: bins of `value`; scatter: `x` against `y`; stats: a row of headline numbers.
 *
 * This interface was referenced by `ProjectManifest`'s JSON-Schema
 * via the `definition` "ChartSpec".
 */
export interface ChartSpec {
	id: string;
	title: string;
	description?: string;
	type: 'bar' | 'donut' | 'histogram' | 'scatter' | 'stats';
	/**
	 * Id of the map layer showing this data: hovering a mark highlights its features there.
	 */
	layer?: string;
	/**
	 * Initial scope: the whole layer (all) or the features in the map view (view). The viewer can switch.
	 */
	scope?: 'all' | 'view';
	format?: ChartFormat;
	data: {
		collection: Collection;
		category?: string;
		value?: string;
		agg?: ChartAgg;
		x?: string;
		y?: string;
		label?: string;
		bins?: number;
		limit?: number;
		/**
		 * Only features intersecting one place (a row of a pub.units__* view), e.g. the town of a map design.
		 */
		within?: {
			unit: string;
			place: string;
		};
		stats?: {
			label: string;
			value?: string;
			agg: ChartAgg;
			format?: ChartFormat;
		}[];
	};
}
