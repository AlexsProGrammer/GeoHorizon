# GeoHorizon: Local GIS Viewshed & Line-of-Sight Analyzer

Version 0.1.1

An offline-first, high-performance, and DSGVO-compliant web application for calculating highly accurate viewsheds. Originally designed to find the perfect sunset viewpoints by combining base elevation data (DEM) with environmental obstacles (trees, buildings).

> 📦 **Release notes:** See the [CHANGELOG.md](./CHANGELOG.md) for the full version history.

## 🎯 The Goal
To provide a self-hosted platform where users can calculate complex, long-range Line-of-Sight (LoS) maps entirely locally. Unlike cloud-based GIS tools, this application processes massive Raster and Vector datasets using local CPU power, ensuring zero data leakage, zero external API costs, and 100% privacy compliance.

## ✨ Core Features
* **Automated Data Pipeline:** Drop raw `.vrt`/GeoTIFF and OpenStreetMap `.pbf` files into a mapped folder, and the backend automatically converts them into Cloud Optimized GeoTIFFs (COGs) and PostGIS tables.
* **Directional Viewsheds:** Instead of expensive 360° sweeps, set an Azimuth (e.g., 270° West) and Field of View (FOV) cone to calculate specific targets (like sunsets) up to 9x faster.
* **Dynamic Elevation Offsets:** Automatically combines base terrain heights with environmental obstacles (+30m for forests, dynamic heights for buildings).
* **The "Kill Switch":** True background task termination. Instantly kill runaway CPU tasks via WebSockets if radius or point density parameters are set too high.
* **100% DSGVO / GDPR Compliant:** Air-gapped capable. Uses local PMTiles for base maps and self-hosted fonts. No telemetry, no Google/Mapbox API calls.

## 🏗️ Tech Stack
* **Frontend:** React, Vite, MapLibre GL JS, Deck.gl (Hardware-accelerated rendering).
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
│       └── worker/
│           ├── __init__.py   # Celery app config
│           └── ingestion_tasks.py  # Raster (COG) & Vector (PostGIS) tasks
│
└── frontend/                # React & MapLibre UI
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts
    ├── public/              # Self-hosted fonts and static assets
    └── src/
        ├── App.tsx          # Main React component
        ├── components/      # Map panel, Settings sidebar, Progress bars
        ├── map/             # MapLibre and Deck.gl overlays
        └── services/        # WebSocket client and API hooks
```

## Setup Data

- Get .osm.pbf files from [Geofabrik](https://download.geofabrik.de/) and elevation data from [OpenTopography](https://opentopography.org/). Place them in `/data/import/` for ingestion.
- Get .tif/.vrt/.xyz/.meta4 files from [OpenTopography](https://opentopography.org/), [USGS EarthExplorer](https://earthexplorer.usgs.gov/) or [Coverage Map](https://viewfinderpanoramas.org/Coverage%20map%20viewfinderpanoramas_org1.htm). Place them in `/data/import/` for ingestion.

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

## 🗺️ Roadmap

- **Part 2 (current):** Automated data ingestion — COG conversion + OSM → PostGIS pipeline.
- **Part 3:** Viewshed & Line-of-Sight math engine (Rasterio / NumPy / WhiteboxTools) reading from PostGIS with GiST-indexed queries.

## 📝 Changelog

See [CHANGELOG.md](./CHANGELOG.md) for the full history. Highlights:

- **0.1.1** — Automated data ingestion pipeline: GDAL/GIS dependencies, PostGIS models, COG + OSM ingestion tasks, and `/api/ingest` endpoints.
- **0.0.1** — Project initialization with Dockerized FastAPI, Celery, PostgreSQL/PostGIS, and a React/MapLibre frontend.
