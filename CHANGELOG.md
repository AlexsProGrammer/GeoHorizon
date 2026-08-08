# Changelog

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