import type { Map as MlMap } from 'maplibre-gl';

declare global {
	namespace App {
		// interface Error {}
		// interface PageState {}
	}

	interface Window {
		/** Automation hook set by the map viewer (used by the Playwright tests). */
		__spatial?: {
			ready: boolean;
			idle: boolean;
			readonly map: MlMap | undefined;
			renderedCount(layerId: string): number;
		};
		/** Automation hook set by the admin footprint map. */
		__adminMap?: { map: MlMap; ready: boolean; features: number };
	}
}

export {};
