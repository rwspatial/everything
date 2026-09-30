// One-time MapLibre setup shared by every map in the app (viewer, admin footprints).
// MapLibre 6 + a bundler needs the worker URL set once (MapLibre docs, "Vite").
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';

setWorkerUrl(workerUrl);

export {};
