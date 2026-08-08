"""Celery tasks for the viewshed pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import rasterio
import redis

from app.core.db import SessionLocal
from app.engine.area_search import run_area_search
from app.engine.pipeline import run_viewshed_pipeline
from app.engine.viewshed import OBSERVER_HEIGHT_DEFAULT
from app.worker import celery_app

PROCESSED_DIR = Path("/data/processed")

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
)


def _publish_progress(task_id: str, status: str, progress: int, step: str) -> None:
    try:
        redis_client.publish(
            f"task_progress:{task_id}",
            json.dumps(
                {
                    "task_id": task_id,
                    "status": status,
                    "progress": progress,
                    "step": step,
                }
            ),
        )
    except Exception:
        pass


def _write_geotiff(path: str, array: np.ndarray, transform, crs) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=array.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(array, 1)


@celery_app.task(bind=True, name="viewshed.run_pipeline")
def run_viewshed_task(self, params: dict):
    """Run the viewshed pipeline and persist the result GeoTIFF."""
    task_id = self.request.id

    def progress(status: str, pct: int, step: str) -> None:
        _publish_progress(task_id, status, pct, step)

    progress("STARTED", 5, "Starting viewshed pipeline")

    try:
        with SessionLocal() as session:
            result = run_viewshed_pipeline(
                session,
                cog_path=params["cog_path"],
                lat=params["lat"],
                lng=params["lng"],
                radius_km=params["radius_km"],
                azimuth=params["azimuth"],
                fov=params["fov"],
                observer_height=params.get("observer_height", OBSERVER_HEIGHT_DEFAULT),
                tree_height=params.get("tree_height", 30.0),
                building_height=params.get("building_height", 15.0),
                horizon_enabled=params.get("horizon_enabled", False),
                horizon_max_km=params.get("horizon_max_km", 100.0),
                horizon_cache_dir=str(PROCESSED_DIR / "horizon_cache"),
                progress_callback=progress,
            )

        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        out_path = PROCESSED_DIR / f"viewshed_{task_id}.tif"
        _write_geotiff(str(out_path), result["visibility"], result["transform"], result["crs"])

        progress("SUCCESS", 100, "Complete")

        return {
            "viewshed_path": str(out_path),
            "bbox": list(result["bbox"]),
            "crs": result["crs"].to_string(),
            "horizon_pass": result.get("horizon_pass"),
            "horizon_score": result.get("horizon_score"),
        }
    except Exception as exc:
        # Notify the frontend immediately so it can show the error and stop,
        # then re-raise so Celery still records the task as failed.
        progress("FAILURE", 0, f"Calculation failed: {exc}")
        raise


@celery_app.task(bind=True, name="viewshed.run_area_search")
def run_area_search_task(self, params: dict):
    """Run a multi-point area search and persist the scored GeoJSON result."""
    task_id = self.request.id

    def progress(status: str, pct: int, step: str) -> None:
        _publish_progress(task_id, status, pct, step)

    progress("STARTED", 5, "Starting area search")

    try:
        with SessionLocal() as session:
            fc = run_area_search(
                session,
                cog_path=params["cog_path"],
                search_area_geojson=params["search_area"],
                radius_km=params["radius_km"],
                azimuth=params["azimuth"],
                fov=params["fov"],
                grid_step_m=params["grid_step_m"],
                observer_height=params.get("observer_height", OBSERVER_HEIGHT_DEFAULT),
                tree_height=params.get("tree_height", 30.0),
                building_height=params.get("building_height", 15.0),
                horizon_enabled=params.get("horizon_enabled", False),
                horizon_max_km=params.get("horizon_max_km", 100.0),
                horizon_cache_dir=str(PROCESSED_DIR / "horizon_cache"),
                progress_callback=progress,
            )

        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        out_path = PROCESSED_DIR / f"area_{task_id}.json"
        out_path.write_text(json.dumps(fc))

        progress("SUCCESS", 100, "Complete")

        return {
            "result_path": str(out_path),
            "count": fc["meta"]["count"],
            "crs": fc["meta"]["crs"],
        }
    except Exception as exc:
        progress("FAILURE", 0, f"Area search failed: {exc}")
        raise
