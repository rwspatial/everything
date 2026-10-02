// Project manifest + LayerSpec contract (plan §2.1 / §2.2). The contract types are generated from
// contracts/project-manifest.v1.schema.json into contracts.gen.ts (make contracts); this module
// re-exports them next to the viewer's own UI types, so imports stay `$lib/types`.
import type { LayerSpec, ProjectStatus, SourceSpec } from './contracts.gen';

export type {
	BBox,
	InteractionSpec,
	LayerSpec,
	LayerStatus,
	LegendSpec,
	LngLat,
	ParamControl,
	ProjectManifest,
	ProjectStatus,
	RasterCogSource,
	SourceSpec,
	StyleFragment,
	StyleSpec,
	ViewSpec
} from './contracts.gen';

export type SourceType = SourceSpec['type'];

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
