# 05: Frontend (Svelte + MapLibre)

The web app is at **http://localhost:8080/**. It's a static SvelteKit build (Svelte 5, MapLibre GL JS 6) served by the
`frontend` container behind the main proxy.

| URL | What |
|---|---|
| `/` | Landing page: identity, services, contact, and projects tagged `maine` as selected work. Copy lives in `src/lib/site.ts` |
| `/maps` | Project hub: every project in `projects/index.json`, with status badges and what's missing |
| `/p/<slug>` | Map viewer: layer list (toggle, opacity, order, parameters, legend), hover popups, click-to-inspect drawer |
| `/new` | How to add a project (the guided creator arrives in Phase 3) |
| `/projects/...` | The manifests themselves (JSON only, served from the repo's `projects/` folder) |

## Everyday commands

| Command | Does |
|---|---|
| `make up` | Starts everything, building the frontend image the first time |
| `make frontend` | Rebuilds and restarts the app after you change files in `frontend/` |
| `make frontend-dev` | Live-reload dev server at **http://localhost:5173** (edits appear instantly; data still comes from the stack) |
| `make frontend-check` | Type-check (svelte-check) |
| `make e2e` | Browser tests in headless Chromium, with screenshots in `frontend/test-results/screens/` |

These run in containers, so you don't need Node on the host. If you do have Node 24, `cd frontend && npm ci && npm run dev`
also works (it proxies data to `http://localhost:8080`).

## Adding or editing a project: no code, no rebuild

1. Publish the data as a `pub` view (docs/setup/04-data-import.md, "Publishing"), then `make refresh`.
2. Create `projects/<slug>/project.json`. Copy `projects/world-overview/project.json` as a starting point.
3. Add `"<slug>"` to `projects/index.json`.
4. Reload the browser.

Manifest edits show up on reload: the proxy reads `projects/` directly and sends `no-cache`.

### Manifest essentials

```jsonc
{
  "manifestVersion": 1,
  "slug": "flood-risk",                 // must equal the folder name
  "title": "Flood Risk",
  "status": "draft",                    // stub | draft | ready  (hub badge)
  "view": { "center": [-77.0, 38.9], "zoom": 9, "basemap": "positron" },
  "layers": [ /* bottom → top */ ],
  "notes": ["Anything still to do"]     // shown on the hub and in the viewer
}
```

Layer `source.type` picks the adapter:

| `source.type` | For | Required fields |
|---|---|---|
| `tipg-vector` | Most layers. Vector tiles from a `pub` view or function | `collection: "pub.<slug>__<layer>"`; optional `properties`, `params` |
| `tipg-geojson` | Small layers (< ~5,000 features) fetched whole | `collection`; optional `limit` |
| `geojson-url` | A GeoJSON file anywhere | `url` |
| `raster-xyz` | Raster tiles (`{z}/{x}/{y}`) | `tiles: [...]` |
| `raster-cog` | A COG in `data/cog/` served by titiler | `cog: "maine/dem_10m"` (path without `.tif`); optional `rescale: [min, max]`, `colormap` (e.g. `terrain`, `viridis`, `rdylbu_r`), `bidx`, `units` (clicking the map shows the pixel value, e.g. `-11.4 °F`, in the Inspector) |

Other layer fields:
- `style.layers`: MapLibre layer definitions without `id`/`source`/`source-layer` (injected). Omit for a default style.
- `legend`: `categorical` (items), `gradient` (stops), `single`, or `none`.
- `interaction.popup.template`: e.g. `"{name}: {pop_est} people"`. `interaction.inspect: false` turns off click details.
- `controls`: sliders bound to SQL function arguments, e.g. `{"param": "max_scalerank", "label": "Max rank", "type": "range", "min": 0, "max": 12}`.
- `status: "todo"` + `todo: "…"`: shown greyed out with the note, never requested from the server.

If a manifest is broken, the hub shows it as an **Error** card with the reason (bad JSON, slug mismatch, unknown
`source.type`, duplicate layer id) and the other projects keep working.

## Shareable views

The viewer keeps its state in the URL: map position (`map=zoom/lat/lon`), visible layers (`v`), order (`o`), opacity (`op`),
function parameters (`pa.<layer>.<param>`) and basemap (`b`). **Copy link** copies it.

## Basemaps

| Key (manifest `view.basemap`) | Menu label | Source |
|---|---|---|
| `positron` (default) | Light (OpenFreeMap) | OpenFreeMap vector tiles |
| `liberty` | Streets (OpenFreeMap) | OpenFreeMap vector tiles |
| `aerial-labels` | Aerial + labels (Esri) | Esri World Imagery + Esri boundaries/places overlay |
| `aerial` | Aerial (Esri) | Esri World Imagery only (cleanest for analysis) |
| `osm-raster` | OpenStreetMap (raster) | tile.openstreetmap.org |
| `none` | None (works offline) | plain background |

Every project gets all of them in the **Basemap** menu. Set `"basemap": "aerial-labels"` in a manifest's `view` to make
one the project's default. Aerial imagery looks best with semi-transparent fills; use the layer's opacity slider or
`"opacity": 0.5` in the manifest.

**Esri imagery terms:** attribution is shown automatically and is required. Esri's basemap tiles are fine for development
and non-commercial use without a key. A public or commercial deployment (Phase 6) needs an ArcGIS Location Platform
account and API key, or an open alternative such as EOX Sentinel-2 cloudless (10 m, CC BY-NC-SA for 2018+ editions).

All of these except `none` need the internet (OpenFreeMap and Esri need no API key locally). `none` is a plain background
that works offline. If an online basemap can't be reached, the viewer falls back to `none` automatically and says so.
Project data is unaffected either way. Project layers are drawn under the basemap's labels so place names stay readable.

## Layout of `frontend/`

```
src/lib/types.ts          manifest + layer contract (Phase 3 generates this from JSON Schema)
src/lib/adapters.ts       source.type → MapLibre source/layers (the extension point)
src/lib/projects.ts       ProjectRepository: static JSON now, core-api in Phase 3
src/lib/basemaps.ts       basemap registry
src/lib/components/       Viewer, LayerTree, Legend, Inspector, StatusBadge
src/routes/               / (landing), /maps (hub), /p/[slug] (viewer), /new
static/config.json        runtime URLs (tiles, projects), swappable without rebuilding
tests/app.spec.ts         Playwright + axe browser tests
```

## Troubleshooting

- **Blank map, layers listed:** check the status bar. "N layers failed" means tiPG returned errors (`make logs s=tipg`).
  A layer with a red **Error** badge shows the message in the layer list.
- **Changes to `frontend/` don't show:** run `make frontend` (the container serves a build), or use `make frontend-dev`.
- **New project doesn't appear:** is its slug in `projects/index.json`, and does `http://localhost:8080/projects/<slug>/project.json` load?
