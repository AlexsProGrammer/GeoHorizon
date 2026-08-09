# GeoHorizon: Local GIS Viewshed & Line-of-Sight Analyzer

Version 0.1.12

An offline-first, high-performance, and DSGVO-compliant web application for calculating highly accurate viewsheds. Originally designed to find the perfect sunset viewpoints by combining base elevation data (DEM) with environmental obstacles (trees, buildings).

> 📦 **Release notes:** See the [CHANGELOG.md](./CHANGELOG.md) for the full version history.

## 🎯 The Goal
To provide a self-hosted platform where users can calculate complex, long-range Line-of-Sight (LoS) maps entirely locally. Unlike cloud-based GIS tools, this application processes massive Raster and Vector datasets using local CPU power, ensuring zero data leakage, zero external API costs, and 100% privacy compliance.

## ✨ Core Features
* **Automated Data Pipeline:** Drop raw `.vrt`/GeoTIFF and OpenStreetMap `.pbf` files into a mapped folder, and the backend automatically converts them into Cloud Optimized GeoTIFFs (COGs) and PostGIS tables.
* **Viewshed Engine (Part 3):** A localized COG extraction + DSM builder that overlays PostGIS obstacle geometries (buildings, forests) onto terrain, combined with a fast in-memory NumPy line-of-sight engine (WhiteboxTools remains available as a `VIEWSHED_ENGINE=whitebox` fallback).
* **Directional & Panoramic Viewsheds:** Instead of expensive 360° sweeps, set an Azimuth (e.g., 270° West) and Field of View (FOV) cone to calculate specific targets (like sunsets) up to 9x faster — or slide FOV to 360° for a full panoramic viewshed with a single click.
* **Area Search (Best-Position Finder):** Draw a search area on the map (any polygon), set a grid step, and the engine scores every sampled position inside it by sky-visibility ratio. Every point runs a full viewshed, so you find the hilltop with the clearest western sunset view (or 360° panorama) — the DEM and DSM are built once and reused across all sampled points, visibility is computed in-memory (no disk I/O), the grid is parallelized across Celery workers, and the Grid Step slider shows a live estimate of the sampled point count <i>before</i> you run.
* **Color-Coded Results & Legend:** Point and area-search results are colored green (≥70% sky visibility), yellow (30–70%), or red (<30%), with a toggleable legend in the sidebar so you can isolate just the best spots.
* **Long-Range Horizon Check:** An optional 100 km horizon ray-cast that catches distant mountains blocking the view even when the local radius looks clear. Long rays are cached per direction and reused across all sampled points, so the check stays fast.
* **3D Terrain & Interactions:** MapLibre 3D terrain (terrain-RGB tiles generated from the DEM on demand) so hills and valleys render realistically, a clickable compass to reset north, a mouse-hover tooltip with coordinates/elevation/OSM labels, and a shared depth buffer that prevents overlay z-fighting when rotating.
* **Dynamic Elevation Offsets:** Automatically combines base terrain heights with environmental obstacles (+30m for forests, dynamic heights for buildings).
* **Windowed COG Reads:** Never loads full regional DEMs into RAM — only the observer's bounding box is read via `rasterio.windows.from_bounds()`.
* **The "Kill Switch":** True background task termination. Instantly kill runaway CPU tasks via WebSockets if radius or point density parameters are set too high.
* **100% DSGVO / GDPR Compliant:** Air-gapped capable. Uses local PMTiles for base maps and self-hosted fonts. No telemetry, no Google/Mapbox API calls.

## 🏗️ Tech Stack
* **Frontend:** React, Vite, MapLibre GL JS (native vector overlays draped on the 3D terrain).
* **Backend:** Python, FastAPI, WebSockets.
* **Processing Engine:** Celery, Redis, NumPy, Rasterio, WhiteboxTools, rio-cogeo, Pyrosm, GeoPandas.
* **Database:** PostgreSQL with PostGIS extension (GeoAlchemy2 + Alembic migrations).
* **Infrastructure:** Docker & Docker Compose (Monorepo).

## 📂 Monorepo Structure

```text
geo-horizon/
├── .env.example             # Global environment variables
├── .gitignore               # Ignored local files (data/, .env)
├── README.md                # Project documentation
├── CHANGELOG.md             # Version history
│
├── docker/                  # Infrastructure orchestration & images
│   ├── docker-compose.yml       # Core service orchestration (db, redis, api, worker, frontend)
│   ├── backend.Dockerfile       # FastAPI + Celery image (baked with GDAL)
│   └── frontend.Dockerfile      # React/Vite dev image
│
├── data/                    # Local Docker volume mounts (ignored in git)
│   ├── import/              # Drop raw .vrt, .tif, and .pbf files here
│   ├── processed/           # System-generated COGs (raster output)
│   ├── pmtiles/             # Local offline map tiles
│   └── postgres_data/       # Persistent database storage
│
├── backend/                 # Python FastAPI & Celery Engine
│   ├── alembic.ini
│   ├── alembic/             # Database migrations (buildings & forests tables)
│   ├── requirements.txt
│   └── app/
│       ├── main.py          # FastAPI entry point, lifespan, router wiring
│       ├── api/
│       │   ├── __init__.py
│       │   └── ingest.py     # Ingestion API routes (scan / start / status)
│       ├── core/
│       │   ├── __init__.py
│       │   └── db.py         # SQLAlchemy engine, SessionLocal, Base
│       ├── models/
│       │   ├── __init__.py
│       │   └── gis.py        # Building & Forest PostGIS models
│       ├── engine/           # GIS Math: Rasterio, NumPy, WhiteboxTools (Part 3)
│       │   ├── __init__.py
│       │   ├── area_search.py    # Multi-point area search & best-position scoring
│       │   ├── dsm_builder.py   # COG extraction & obstacle height matrix addition
│       │   ├── horizon_profiler.py # 100km horizon ray casts (cached .npz profiles)
│       │   ├── terrain_tiles.py  # Terrain-RGB PNG tiles for 3D terrain
│       │   ├── cone_filter.py   # Spatial azimuth & FOV cone calculation
│       │   ├── numpy_viewshed.py # In-memory NumPy viewshed engine (default)
│       │   ├── viewshed.py      # WhiteboxTools viewshed execution wrapper (fallback)
│       │   ├── pipeline.py     # Main execution coordinator function
│       │   └── benchmark.py    # Area-search perf benchmark (`python -m app.benchmark`)
│       └── worker/
│           ├── __init__.py   # Celery app config
│           ├── ingestion_tasks.py  # Raster (COG) & Vector (PostGIS) tasks
│           └── viewshed_tasks.py   # Viewshed pipeline + parallel area-search orchestrator
│
└── frontend/                # React & MapLibre UI
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    ├── public/              # Self-hosted fonts and static assets
    │   └── style.json       # MapLibre style referencing local PMTiles
    └── src/
        ├── App.tsx          # Main layout (Sidebar + Map + ProgressBar)
        ├── main.tsx         # Entry point (local fonts + Tailwind)
        ├── index.css        # Tailwind directives
        ├── store/
        │   └── useMapStore.ts   # Zustand state: parameters, task, progress, result
        ├── components/
        │   ├── Sidebar.tsx      # Settings panel (sliders, Calculate/Kill buttons)
        │   ├── ProgressBar.tsx  # WebSocket-driven loading UI
        │   └── MapView.tsx      # MapLibre GL map container
        ├── hooks/
        │   └── useTaskWebSocket.ts  # WebSocket progress client
        └── services/
            ├── api.ts           # API fetch wrappers
            └── geometry.ts      # Cone-preview + circle search-area polygon generators
```

## Setup Data

- Get .pbf files from [Geofabrik](https://download.geofabrik.de/) or [OpenStreetMap Extracts](https://extract.bbbike.org/). Place in `/data/import/` for ingestion.
- Get .tif/.vrt/.xyz/.meta4 files from [OpenTopography](https://opentopography.org/), [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or [Coverage Map](https://viewfinderpanoramas.org/Coverage%20map%20viewfinderpanoramas_org1.htm). Place in `/data/import/` for ingestion.

  If you get a .vrt/.xyz/.meta4 file:
```bash
# Skip if you have already .vrt/.tif/.xyz files. Only if its a .meta4 file.
sudo apt install -y aria2
aria2c --follow-metalink=mem your_file.meta4
sudo apt update && sudo apt install -y unzip gdal-bin
mkdir extracted_tiles && unzip '*.zip' -d extracted_tiles
cd extracted_tiles

# If its a bunch of .tif files use:
gdal_merge.py -o ../merged_dgm.tif -co COMPRESS=DEFLATE -co TILED=YES extracted_tiles/*.tif
# If its a bunch of .xyz use:
gdal_merge.py -o ../merged_dgm.tif -co COMPRESS=DEFLATE -co TILED=YES extracted_tiles/*.xyz
# If its a bunch of .txt files use:
gdalbuildvrt combined_blueprint.vrt *.txt
gdal_translate -of GTiff -co COMPRESS=DEFLATE -co TILED=YES combined_blueprint.vrt ../merged_dgm.tif
```

Download .mbtiles from [OpenFreeMap](https://openfreemap.org/):
```bash
# Convert to .pmtiles using gdal:
ogr2ogr basemap.pmtiles input.mbtiles 
```

## 🚀 Getting Started (Development)

1. Clone the repository.
2. Copy `.env.example` to `.env` and adjust credentials if needed.
3. Place your local base map `.pmtiles` inside `/data/pmtiles/`.
4. Run the stack (from the repository root):
```bash
docker compose -f docker/docker-compose.yml up --build -d
```
5. Access the UI at `http://localhost:3002` (frontend), API docs at `http://localhost:8000/docs`, and the database on `localhost:5436`.
6. Drop your elevation (`.vrt` / `.tif`) and vector (`.pbf`) data into `/data/import/`, then trigger ingestion through the API (see below) or the UI to prime the database.

> **Note:** The `db`, `redis`, `api`, and `worker` services all resolve each other by container name over the `horizon-net` bridge network. Only `db` (5436), `api` (8000), and `frontend` (3002) are published to the host.

## 🗺️ PMTiles Base Map

The frontend requires a local `.pmtiles` base map for offline/DSGVO-compliant rendering:

1. Download a PMTiles file for your region from [OpenFreeMap](https://openfreemap.org/) or generate one with [planetiler](https://github.com/onthegomap/planetiler).
2. Place the file at `data/pmtiles/basemap.pmtiles`.
3. The backend serves it statically at `/tiles/basemap.pmtiles`.
4. Update `frontend/public/style.json` if your tile schema differs from the default (vector source with an OpenMapTiles-compatible schema is assumed).

## 🔄 Ingestion Pipeline

The backend automatically watches `/data/import/` for new datasets. The flow is **Scan → Start → Status**:

1. **Scan** lists every loadable file in `/data/import/` and classifies it as `raster` (`.tif`/`.vrt`) or `vector` (`.pbf`).
2. **Start** dispatches the matching background Celery task:
   - **Raster** → converted to a Cloud Optimized GeoTIFF (COG) with DEFLATE compression and internal overviews, written to `/data/processed/`.
   - **Vector** → parsed offline with Pyrosm; buildings and forests (OSM `natural=wood` / `landuse=forest`) are written to PostGIS with GiST spatial indexes and default estimated heights (10m buildings, 30m forests).
3. **Status** polls the task until it reaches `SUCCESS` or `FAILURE`.

Both tasks run asynchronously in the `worker` container, so large files never block the API.

## 🔌 API Reference

Base URL: `http://localhost:8000`

### `GET /api/ingest/scan`
Lists all supported files currently in `/data/import/`.

**Response:**
```json
{
  "files": [
    { "name": "elevation.tif", "type": "raster", "size": 4098239 },
    { "name": "monaco.pbf",     "type": "vector", "size": 811223   }
  ]
}
```

### `POST /api/ingest/start`
Starts processing a single file. Requires the filename exactly as returned by `scan`.

**Request body:** `{ "filename": "monaco.pbf" }`

**Response:** `{ "task_id": "8e3f…", "type": "vector" }`

### `GET /api/ingest/status/{task_id}`
Returns the current state of a started task.

**Response:** `{ "task_id": "8e3f…", "state": "SUCCESS", "result": { ... }, "error": null }`

| State | Meaning |
|-------|---------|
| `PENDING` | Queued, waiting for a worker |
| `STARTED` | Currently being processed |
| `SUCCESS` | Completed; `result` holds the output summary |
| `FAILURE` | Failed; `error` holds the exception message |

Interactive documentation (OpenAPI) is available at `/docs` and `/redoc`.

## 🔭 Viewshed Engine

The viewshed engine (`backend/app/engine/`) computes high-accuracy line-of-sight maps from the ingested COGs and PostGIS obstacle data:

1. **Bounding Box** — `get_bounding_box(lat, lng, radius_km, src_crs)` transforms the observer from WGS84 (EPSG:4326) into the DEM's projected CRS via `pyproj` and derives a square coverage box.
2. **COG Window Read** — `crop_dem_window(cog_path, bbox)` reads only the needed elevation window with `rasterio.windows.from_bounds()`, keeping RAM usage constant regardless of DEM size.
3. **Obstacle Overlay** — `fetch_obstacles(db, bbox)` runs `ST_Intersects` queries against the `buildings` and `forests` tables; `build_dsm(...)` rasterizes them into height masks and adds them to the DEM: `dsm = dem + tree_mask + building_mask`.
4. **Viewshed** — by default `numpy_viewshed(...)` computes the visibility mask in-memory (no external process, no disk I/O); the legacy path uses `calculate_viewshed(dsm, ...)`, which exports the DSM as a temporary GeoTIFF, runs WhiteboxTools' multi-core `viewshed`, and reads back the binary visibility raster (1 = visible, 0 = blocked). WhiteboxTools is selected with `VIEWSHED_ENGINE=whitebox`.
5. **Directional Cone** — `create_directional_mask(...)` keeps only cells inside the `[azimuth ± FOV/2]` wedge and within the radius, cutting computation dramatically vs. a 360° sweep. Its meshgrid geometry is precomputed once per DSM and reused across all points.

The full flow is orchestrated by `run_viewshed_pipeline(...)` in `pipeline.py` and executed in the background as a Celery task.

The **area search** engine (`area_search.py`) builds on this flow to find the best positions inside a user-drawn polygon: it crops the DEM and builds the DSM *once* for the whole area, writes it once for the legacy engine, and runs an in-memory NumPy viewshed from every grid point (computed in parallel across Celery workers in `worker/viewshed_tasks.py`), scoring each by `visible cells / cells in the cone`. The scored points are returned as GeoJSON for the frontend to display. The cone-filter geometry and horizon profiles are precomputed once and shared across all points.

The **horizon profiler** (`horizon_profiler.py`) casts optional long-range rays (default 100 km, one every ~5° within the FOV, 72 even rays for 360°) to detect distant mountains. Terrain elevations along each ray are sampled once, Earth-curvature-corrected, and cached to `/data/processed/horizon_cache/` as `.npz` per direction — every observer in an area search reuses the same profiles. When enabled, a position's score is `local_visibility × horizon_clear_fraction`.

### `POST /api/viewshed/start`
Dispatches a single-point viewshed as a background Celery task. The observer is wrapped in a
circular search area of the configured `radius_km` and scored by the same multi-point engine as
area mode, so it returns the same scored GeoJSON result. `fov >= 360` selects panoramic scoring.

**Request body:**
```json
{
  "cog_path": "/data/processed/elevation_cog.tif",
  "lat": 43.731,
  "lng": 7.419,
  "radius_km": 5.0,
  "azimuth": 270,
  "fov": 40,
  "observer_height": 1.8,
  "tree_height": 30.0,
  "building_height": 15.0,
  "point_density": null
}
```

**Response:** `{ "task_id": "8e3f…" }`

### `POST /api/viewshed/area-search`
Dispatches a multi-point area search as a background Celery task. Finds the best viewing positions inside the given search area by scoring every grid point with a sky-visibility ratio.

**Request body:**
```json
{
  "cog_path": "/data/processed/elevation_cog.tif",
  "search_area": { "type": "Polygon", "coordinates": [[[12.6, 47.9], ...]] },
  "radius_km": 5.0,
  "azimuth": 270,
  "fov": 40,
  "grid_step_m": 50,
  "observer_height": 1.8,
  "tree_height": 30.0,
  "building_height": 15.0,
  "horizon_enabled": false,
  "horizon_max_km": 100.0
}
```
`search_area` is a GeoJSON Polygon in WGS84 (drawn on the frontend). `grid_step_m` controls sampling density (coarser = faster).

**Response:** `{ "task_id": "8e3f…" }`

Progress is streamed over the same `WS /ws/progress/{task_id}` channel (`PREPARING_AREA` → `BUILDING_DSM` → `SAMPLING` → `CALCULATING` with per-point updates).

### `GET /api/viewshed/result/{task_id}` (alias: `/api/viewshed/area-result/{task_id}`)
Returns the scored result of a point or area search as a GeoJSON `FeatureCollection`. Point mode
now produces the same result format as area mode (a circular area around the observer is scored),
so a single endpoint serves both. Each feature is a Point with a `score` property (0.0–1.0 =
sky-visibility ratio); a `meta.count` field reports the number of sampled points.

```json
{
  "type": "FeatureCollection",
  "features": [
    { "type": "Feature", "properties": { "score": 0.87 }, "geometry": { "type": "Point", "coordinates": [12.6111, 47.9123] } }
  ],
  "meta": { "crs": "EPSG:25832", "count": 156 }
}
```

### `GET /api/viewshed/status/{task_id}`
Returns the task state and, on success, the result metadata. For both point and area searches the
final result is the scored GeoJSON written to `/data/processed/area_{task_id}.json`. Because the
area-search orchestrator dispatches a Celery chord and returns before the merge callback persists
the result, this endpoint reports `SUCCESS` only once that file actually exists (so the frontend
never races ahead of the merge).

### `GET /api/viewshed/terrain/{z}/{x}/{y}.png`
Returns a Mapbox terrain-RGB PNG tile for the MapLibre 3D terrain. The tile is warped from the first available processed COG into Web-Mercator, elevation-encoded as terrain-RGB, and cached to `/data/processed/terrain_cache/`. The frontend uses this as a `raster-dem` source with `map.setTerrain(...)`.

**Response headers:** `Content-Type: image/png`, `Cache-Control: public, max-age=86400`

### `GET /api/viewshed/bounds`
Lists all processed COGs in `/data/processed/` with their spatial metadata, so the frontend knows valid calculation boundaries.

**Response:**
```json
{
  "cogs": [
    {
      "name": "elevation_cog.tif",
      "path": "/data/processed/elevation_cog.tif",
      "crs": "EPSG:25832",
      "extent": [754000.0, 5289000.0, 798000.0, 5332000.0],
      "extent_epsg4326": [12.61, 47.62, 13.41, 48.12],
      "pixel_size_m": 5.0,
      "shape": [8600, 8800],
      "nodata": null
    }
  ]
}
```

### `GET /api/viewshed/elevation?lng={lng}&lat={lat}`
Returns the absolute elevation (meters above sea level) sampled **directly from the first
processed COG** at the given WGS84 coordinate. Used by the hover tooltip so the elevation is
always correct even after panning/zooming (unlike MapLibre's client-side terrain read, which
returns `0` whenever the point's DEM tile is no longer cached).

**Response:** `{ "elevation": 576.67 }` (or `{ "elevation": null }` when the point is outside
the DEM extent or is a no-data pixel).

### `POST /api/viewshed/cancel/{task_id}`
The **Kill Switch**. Hard-terminates a running viewshed task by revoking the Celery process with `SIGKILL`, so heavy native computation (WhiteboxTools / GDAL) stops instantly.

**Response:** `{ "task_id": "8e3f…", "status": "CANCELLED" }`

### `WS /ws/progress/{task_id}`
Connect for real-time progress of a viewshed task. The server subscribes to the Redis channel `task_progress:{task_id}` and forwards each update verbatim as JSON text:

```json
{ "task_id": "8e3f…", "status": "BUILDING_DSM", "progress": 30, "step": "Overlaying obstacles" }
```

The first frame is always `{ "status": "CONNECTED", "progress": 0 }`; a cancellation arrives as `{ "status": "CANCELLED", "progress": 0, "message": "Task killed by user" }`.

## 📦 Configuration

Environment variables live in `.env` (see `.env.example`):

| Variable | Description |
|----------|-------------|
| `POSTGRES_USER` | Database user |
| `POSTGRES_PASSWORD` | Database password (change in production) |
| `POSTGRES_DB` | Database name |
| `DATABASE_URL` | SQLAlchemy connection string (used by API, worker, Alembic) |
| `REDIS_URL` | Redis connection URL |
| `CELERY_BROKER_URL` | Celery broker (Redis) |
| `CELERY_RESULT_BACKEND` | Celery result backend (Redis) |
| `VIEWSHED_ENGINE` | Viewshed engine: `auto`/`numpy` (in-memory, default) or `whitebox` (WhiteboxTools fallback) |
| `WORKER_CONCURRENCY` | Number of Celery worker processes for parallel area-search batches |

## 🗺️ Roadmap

- **Part 2 (done):** Automated data ingestion — COG conversion + OSM → PostGIS pipeline.
- **Part 3 (done):** Viewshed & Line-of-Sight math engine (Rasterio / NumPy / WhiteboxTools) reading from PostGIS with GiST-indexed queries.
- **Part 4 (done):** Real-time task progress via WebSocket (`/ws/progress/{task_id}`), hard Kill Switch (`/api/viewshed/cancel/{task_id}`), and COG bounds endpoint.
- **Part 5 (done):** Interactive frontend — MapLibre GL JS + Deck.gl overlay with a local PMTiles base map, directional cone preview, real-time progress bars, and the Kill Switch cancel button.

## 📝 Changelog

See [CHANGELOG.md](./CHANGELOG.md) for the full history. Highlights:

- **0.1.11** — Area-search performance overhaul: a fast in-memory NumPy viewshed replaced per-point WhiteboxTools + disk I/O, the DSM and horizon profiles are built once and shared, grid points run in parallel across Celery workers, the cone-filter meshgrid is precomputed, and the grid-step slider shows a live point-count estimate. `python -m app.benchmark` validates the speedup and a CI workflow asserts >=4×.
- **0.1.12** — Unified point & area modes (both return scored GeoJSON; point mode scores a circular area around the observer), a 360°/Directional view-direction toggle with discrete panoramic scoring, removed the fading/drifting Deck.gl green mask (all results are now native MapLibre layers glued to the 3D terrain), and fixed the area-search Celery task (chord-based merge, no more `result.get()` crash or premature DSM deletion).
- **0.1.10** — Bug fixes: corrected the terrain-RGB encoding, made hover elevation read the absolute DEM height from the COG directly, busted stale terrain tiles, converted interactive overlays to native MapLibre vector layers, fixed map/hover lag (lazy Deck.gl overlay + skip hover queries while moving), and raised the 3D camera `maxPitch` to 85° so you can get a near-ground view without clipping.
- **0.1.9** — 3D terrain (terrain-RGB tiles + MapLibre `setTerrain`), z-fighting fix via shared depth buffer, a clickable north-resetting compass, and a mouse-hover tooltip with coordinates, elevation, and OSM feature labels.
- **0.1.8** — Long-Range Horizon Check: an optional 100 km ray-cast detects distant mountains blocking the view. Profiles are Earth-curvature-corrected and cached per direction (`/data/processed/horizon_cache/`), then reused across all area-search points; a "Horizon check" toggle feeds into the area score (`local × horizon`).
- **0.1.7** — Color-coded results: area-search positions are now rendered green (≥70%), yellow (30–70%), or red (<30%) and a toggleable legend in the sidebar lets you show/hide each quality class on the map.
- **0.1.6** — Area Search (best-position finder): draw a search polygon on the map and the engine scores every sampled grid point by sky-visibility ratio using a single reused DSM. New `/api/viewshed/area-search` + `/api/viewshed/area-result/{task_id}` endpoints, an Analysis Mode toggle (Point/Area), configurable grid step, and a scored-point scatter overlay.
- **0.1.5** — 360° Panoramic Viewshed: FOV can now be set to 360° for a full circular line-of-sight, alongside the existing directional cone mode. The engine skips the directional mask and produces a symmetric panoramic result; the map preview renders a full circle instead of a wedge.
- **0.1.4** — Interactive frontend: MapLibre GL + Deck.gl UI with a local PMTiles base map, directional cone preview, real-time progress bars, Kill Switch button, and PNG viewshed result overlay.
- **0.1.3** — Real-time progress via WebSockets, hard Kill Switch (SIGKILL revoke), COG bounds endpoint, tuned Celery config.
- **0.1.2** — Viewshed engine: COG windowed reads, DSM builder with PostGIS obstacle overlay, directional cone filter, WhiteboxTools viewshed, and a Celery-backed pipeline (`/api/viewshed`).
- **0.1.1** — Automated data ingestion pipeline: GDAL/GIS dependencies, PostGIS models, COG + OSM ingestion tasks, and `/api/ingest` endpoints.
- **0.0.1** — Project initialization with Dockerized FastAPI, Celery, PostgreSQL/PostGIS, and a React/MapLibre frontend.
