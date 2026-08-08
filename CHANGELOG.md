# Changelog

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