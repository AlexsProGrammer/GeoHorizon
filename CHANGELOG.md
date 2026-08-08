# Changelog

## [0.1.9] - 2026-08-08
Added 3D terrain, z-fighting fixes, a compass and a hover tooltip:
- **3D terrain:** New `engine/terrain_tiles.py` renders Mapbox terrain-RGB PNG tiles from the DEM COG on demand (Web-Mercator warp + RGB elevation encoding), served at `GET /api/viewshed/terrain/{z}/{x}/{y}.png` and cached to `/data/processed/terrain_cache/`. `MapView` adds a `raster-dem` source and `map.setTerrain(...)` (exaggeration 1.5) so hills and valleys render in 3D.
- **Z-fighting fix:** The Deck.gl `MapboxOverlay` now shares the depth buffer with MapLibre terrain (`parameters: { depthTest: true, blend: true }`), preventing the overlay surfaces from fighting with the 3D relief, especially when rotating.
- **Compass:** New `Compass.tsx` control in the top-right corner showing N/S/E/W that rotates with the map; clicking it eases the view back to north (bearing 0).
- **Hover tooltip:** New `HoverTooltip.tsx` shows live coordinates, terrain elevation, and OSM feature labels (water, road, building, forest, etc.) as you move the mouse, using `queryTerrainElevation` / `queryRenderedFeatures`.

## [0.1.8] - 2026-08-08
Added long-range horizon ray casting with caching (the "mountain 50 km away blocks the view" case):
- **Backend:** New `engine/horizon_profiler.py` module. `compute_horizon_profiles` samples DEM elevation along rays in the requested directions (one every ~5° within the FOV, 72 even rays for 360°) out to 100 km and caches each profile as `.npz` in `/data/processed/horizon_cache/` keyed by COG + azimuth + params.
- **Backend:** Earth-curvature-corrected horizon test. `horizon_fraction` checks whether any terrain beyond the observer, corrected for curvature, rises above eye level (DEM elevation at the observer + observer height); a ray scores 1.0 if clear, 0.0 if blocked.
- **Backend:** Horizon per-direction profiles are computed once relative to the search-area centroid and reused for every sampled point in an area search. When enabled, a position's final score = `local sky-visibility × horizon clear fraction`.
- **Backend:** Single-point pipeline gains optional `horizon_enabled` / `horizon_max_km`; it returns `horizon_pass` / `horizon_score` in the task result.
- **Backend:** New `HorizonProfile` dataclass, `ray_azimuths`, `observer_distance_along_ray`; both `ViewshedRequest` and `AreaSearchRequest` accept `horizon_enabled` / `horizon_max_km`.
- **Tests:** New `tests/test_horizon_profiler.py` covering ray-azimuth generation, flat-vs-mountain horizon blocking, observer projection, and profile caching.
- **Frontend:** "Horizon check (100 km)" checkbox in the sidebar, wired into both the area-search and single-point request payloads.

## [0.1.7] - 2026-08-08
Added color-coded results and a toggleable legend for area-search positions:
- **Frontend:** Area-search scatter results are now colored by sky-visibility score instead of a flat green — green (≥0.70), yellow (0.30–0.70), red (<0.30).
- **Frontend:** New `Legend` component shown in the sidebar whenever a scored area result is present. Each quality band (Excellent/Moderate/Poor) has a checkbox that toggles whether that color is drawn on the map, isolating just the best spots.
- **Frontend:** Store gains a `legendVisibility` state + `toggleLegendColor` action; `MapView` filters the rendered scatter features accordingly and colors them per-threshold.

## [0.1.6] - 2026-08-08
Added the multi-point area search engine for finding the best viewing positions inside a user-drawn area:
- **Backend:** New `engine/area_search.py` module. It transforms the WGS84 search polygon into the DEM CRS, crops the DEM window and builds the DSM **once** for the whole area, samples a regular grid of points at a configurable step, runs a WhiteboxTools viewshed from every point, and scores each by sky-visibility ratio (visible cells / cells in the viewing cone).
- **Backend:** New Celery task `viewshed.run_area_search` persisting the scored result as GeoJSON (`/data/processed/area_{task_id}.json`) and streaming stage-by-stage progress (`PREPARING_AREA`, `BUILDING_DSM`, `SAMPLING`, `CALCULATING`).
- **Backend:** New endpoints `POST /api/viewshed/area-search` and `GET /api/viewshed/area-result/{task_id}`.
- **Backend:** New `AreaSearchRequest` model (`cog_path`, `search_area` GeoJSON, `radius_km`, `azimuth`, `fov`, `grid_step_m`, heights).
- **Tests:** New `tests/test_area_search.py` covering grid sampling, sky-ratio scoring, and the scored FeatureCollection output.
- **Frontend:** "Analysis Mode" toggle in the sidebar (Point / Area). In Area mode the user draws a polygon on the map (click to add vertices, "Finish area" to close) with a live draft preview, sets a grid-step slider, and runs a Search Area task.
- **Frontend:** Result rendered as a scored green scatter overlay via Deck.gl `ScatterplotLayer`; the single-point flow is unchanged.

## [0.1.5] - 2026-08-08
Added 360° panoramic viewshed support on top of the existing directional cone mode:
- **Backend:** The viewshed pipeline now treats `fov >= 360` as a full panoramic sweep. It skips the directional wedge and applies a simple circular radius mask instead, producing a symmetric 360° line-of-sight result. Directional cone behaviour is unchanged for `fov < 360`.
- **Tests:** Added `test_pipeline_panoramic_mask_is_circular` verifying the 360° output is a full circle with no directional bias.
- **Frontend:** FOV slider now spans up to 360°. At 360° the label switches to "Field of View (Panoramic)" and the live map preview renders a full circle polygon instead of a wedge (`buildConePolygon` handles the panoramic sweep).

## [0.1.4] - 2026-08-08
Implemented the interactive frontend UI for viewshed visualization (Part 5):
- MapLibre GL JS base map with local PMTiles support for DSGVO-compliant offline rendering.
- Deck.gl hardware-accelerated overlay layers for the directional cone preview and the viewshed result visualization.
- Interactive control sidebar with parameter sliders (radius, azimuth, FOV, tree/building offsets).
- Live geometric cone preview on the map that updates in real-time as parameters change.
- Zustand state management for observer position, parameters, task progress, and result data.
- Real-time progress bar driven by a WebSocket connection to `/ws/progress/{task_id}`.
- Kill Switch cancel button with hard task termination via `/api/viewshed/cancel/{task_id}`.
- PNG viewshed result endpoint (`GET /api/viewshed/result/{task_id}/image`) converting GeoTIFF output to Deck.gl BitmapLayer-compatible images.
- Fixed Vite proxy configuration to properly route API requests through the development proxy.
- Local font bundling via @fontsource/inter — zero external requests.
- Tailwind CSS for styling with Lucide React icons.

## [0.1.3] - 2026-08-08
Implemented real-time task progress and a hard Kill Switch (Part 4):
- WebSocket endpoint `/ws/progress/{task_id}` streaming Redis Pub/Sub progress frames to the frontend in real time.
- Hard "Kill Switch" endpoint `POST /api/viewshed/cancel/{task_id}` revoking the Celery process with `SIGKILL` to instantly stop runaway CPU calculations.
- COG bounds endpoint `GET /api/viewshed/bounds` exposing spatial extent, CRS, and resolution of processed COGs for frontend map configuration.
- Celery configuration tuned for reliability: `task_track_started`, `result_expires=3600`, and `worker_prefetch_multiplier=1`.
- Viewshed pipeline now publishes stage-by-stage progress (FETCHING_DEM → BUILDING_DSM → COMPUTING_VIEWSHED → APPLYING_CONE → SUCCESS) via Redis.
- Added optional `point_density` field to the viewshed request model for future use.

## [0.1.2] - 2026-08-08
Implemented the core geospatial viewshed engine (Part 3):
- COG windowed read extraction via bounding box (never loads full DEMs into RAM).
- Digital Surface Model (DSM) builder: PostGIS obstacles (buildings + forests) rasterized and added to terrain.
- Directional cone filter (azimuth + FOV) for selective viewing angle calculation.
- WhiteboxTools viewshed execution for multi-core line-of-sight maps.
- Pipeline orchestrator connecting BBOX → DSM → viewshed → cone filter, exposed as a Celery task with `/api/viewshed` endpoints.

## [0.1.1] - 2026-08-08
Standardized project version to 0.1.1 across README, CHANGELOG, FastAPI, and frontend. Prepared ground-work for the data ingestion pipeline (environment, dependencies, models, worker tasks, and API endpoints are built out in subsequent phases).

## [0.0.1] - 2026-08-07
Init Project, with Dockerized FastAPI backend, Celery worker, PostgreSQL/PostGIS database, and React frontend with MapLibre GL JS and Deck.gl for hardware-accelerated rendering. Added support for processing elevation (.vrt/.tif) and vector (.pbf) data to generate viewsheds and line-of-sight analyses.