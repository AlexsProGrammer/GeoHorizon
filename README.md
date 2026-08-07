
# GeoHorizon: Local GIS Viewshed & Line-of-Sight Analyzer

Version 0.0.1

An offline-first, high-performance, and DSGVO-compliant web application for calculating highly accurate viewsheds. Originally designed to find the perfect sunset viewpoints by combining base elevation data (DEM) with environmental obstacles (trees, buildings).

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
* **Processing Engine:** Celery, Redis, NumPy, Rasterio, WhiteboxTools.
* **Database:** PostgreSQL with PostGIS extension.
* **Infrastructure:** Docker & Docker Compose (Monorepo).

## 📂 Monorepo Structure

```text
geo-horizon/
├── .env.example             # Global environment variables
├── docker-compose.yml       # Core infrastructure orchestration
├── README.md                # Project documentation
│
├── data/                    # Local Docker volume mounts (ignored in git)
│   ├── import/              # Drop raw .vrt, .tif, and .pbf files here
│   ├── processed/           # System-generated COGs
│   ├── pmtiles/             # Local offline map tiles
│   └── postgres_data/       # Persistent database storage
│
├── backend/                 # Python FastAPI & Celery Engine
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py          # FastAPI entry point & WebSockets
│   │   ├── api/             # API routes
│   │   ├── core/            # Config, database connections
│   │   ├── worker/          # Celery tasks (The Kill Switch lives here)
│   │   └── engine/          # GIS Math: Rasterio, NumPy, WhiteboxTools
│   └── scripts/             # Data ingestion pipeline scripts
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

## 🚀 Getting Started (Development)

1. Clone the repository.
2. Copy `.env.example` to `.env`.
3. Place your local base map `.pmtiles` inside `/data/pmtiles/`.
4. Run the stack:
```bash
docker compose up --build -d

```


5. Access the UI at `http://localhost:3000`.
6. Drop your elevation (`.vrt` / `.tif`) and vector (`.pbf`) data into `/data/import/` and click **"Process New Data"** in the UI to prime the database.
