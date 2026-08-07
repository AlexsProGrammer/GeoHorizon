# Changelog

## [0.1.1] - 2026-08-08
Standardized project version to 0.1.1 across README, CHANGELOG, FastAPI, and frontend. Prepared ground-work for the data ingestion pipeline (environment, dependencies, models, worker tasks, and API endpoints are built out in subsequent phases).

## [0.0.1] - 2026-08-07
Init Project, with Dockerized FastAPI backend, Celery worker, PostgreSQL/PostGIS database, and React frontend with MapLibre GL JS and Deck.gl for hardware-accelerated rendering. Added support for processing elevation (.vrt/.tif) and vector (.pbf) data to generate viewsheds and line-of-sight analyses.