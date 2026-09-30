// Project manifest + LayerSpec contract (plan §2.1 / §2.2).
// Phase 2: hand-written here. Phase 3 generates these types from contracts/*.schema.json.
import type { DistributiveOmit, LayerSpecification } from 'maplibre-gl';

export type ProjectStatus = 'stub' | 'draft' | 'ready';
export type LayerStatus = 'ready' | 'todo';

export interface ProjectManifest {
	manifestVersion: 1;
	slug: string;
	title: string;
	status: ProjectStatus;
	description?: string;
	tags?: string[];
	view: {
		center: [number, number];
		zoom: number;
		bounds?: [number, number, number, number] | null;
		basemap?: string;
	};
	layers: LayerSpec[];
	/** Free-text to-do notes for placeholder projects, shown on the hub and in the viewer. */
	notes?: string[];
}

/** One visual layer. `source.type` selects the frontend adapter (src/lib/adapters.ts). */
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
	style?: { kind: 'maplibre'; layers: StyleFragment[] };
	legend?: LegendSpec;
	interaction?: { popup?: { template: string }; inspect?: boolean };
	/** UI controls bound to tiPG function arguments (source.params). */
	controls?: ParamControl[];
	attribution?: string;
}

export type SourceSpec =
	| {
			type: 'tipg-vector';
			collection: string;
			tms?: string;
			params?: Record<string, string | number>;
			properties?: string[];
			maxzoom?: number;
	  }
	| {
			type: 'tipg-geojson';
			collection: string;
			params?: Record<string, string | number>;
			properties?: string[];
			limit?: number;
	  }
	| { type: 'geojson-url'; url: string }
	| { type: 'raster-xyz'; tiles: string[]; tileSize?: number; maxzoom?: number };

export type SourceType = SourceSpec['type'];

/** A MapLibre layer minus id/source/source-layer, which the adapter injects. */
export type StyleFragment = DistributiveOmit<LayerSpecification, 'id' | 'source' | 'source-layer'>;

export type LegendSpec =
	| { type: 'categorical'; title?: string; items: { label: string; color: string }[] }
	| { type: 'gradient'; title?: string; stops: { value: string; color: string }[] }
	| { type: 'single'; label?: string; color: string }
	| { type: 'none' };

export interface ParamControl {
	param: string;
	label: string;
	type: 'range';
	min: number;
	max: number;
	step?: number;
}

/** Viewer UI state for one layer (array order = draw order, bottom → top). */
export interface LayerState {
	spec: LayerSpec;
	visible: boolean;
	opacity: number;
	params: Record<string, string | number>;
	error: string | null;
	color: string;
}

export interface InspectedFeature {
	layerId: string;
	layerTitle: string;
	properties: Record<string, unknown>;
}

export interface ProjectSummary {
	slug: string;
	title: string;
	status: ProjectStatus;
	description: string;
	tags: string[];
	layerCount: number;
	pendingLayers: { title: string; todo: string }[];
	notes: string[];
	error?: string;
}
