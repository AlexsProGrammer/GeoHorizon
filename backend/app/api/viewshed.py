import json
import os
from pathlib import Path

import rasterio
import redis
from celery.result import AsyncResult
from fastapi import APIRouter
from pydantic import BaseModel
from rasterio.warp import transform_bounds

from app.worker import celery_app
from app.worker.viewshed_tasks import run_viewshed_task

router = APIRouter(prefix="/viewshed", tags=["viewshed"])

PROCESSED_DIR = Path("/data/processed")

_redis = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True
)


class ViewshedRequest(BaseModel):
    cog_path: str
    lat: float
    lng: float
    radius_km: float
    azimuth: float
    fov: float
    observer_height: float = 1.8
    tree_height: float = 30.0
    building_height: float = 15.0
    point_density: int | None = None


@router.post("/start")
async def start(payload: ViewshedRequest):
    task = run_viewshed_task.delay(payload.model_dump())
    return {"task_id": task.id}


@router.get("/status/{task_id}")
async def status(task_id: str):
    result: AsyncResult = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "state": result.state,
        "result": result.result if result.successful() else None,
        "error": str(result.info) if result.failed() else None,
    }


@router.post("/cancel/{task_id}")
async def cancel(task_id: str):
    """Hard-kill a running viewshed task.

    Revokes the Celery task with SIGKILL so any heavy native computation
    (WhiteboxTools / GDAL) is terminated immediately.
    """
    celery_app.control.revoke(task_id, terminate=True, signal="SIGKILL")

    try:
        _redis.publish(
            f"task_progress:{task_id}",
            json.dumps(
                {
                    "status": "CANCELLED",
                    "progress": 0,
                    "message": "Task killed by user",
                }
            ),
        )
    except Exception:
        pass

    out_path = PROCESSED_DIR / f"viewshed_{task_id}.tif"
    if out_path.exists():
        out_path.unlink()

    return {"task_id": task_id, "status": "CANCELLED"}


@router.get("/bounds")
async def bounds():
    """Return the spatial extent and metadata of processed COGs."""
    cogs = []
    if PROCESSED_DIR.is_dir():
        for path in sorted(PROCESSED_DIR.glob("*_cog.tif")):
            try:
                with rasterio.open(path) as src:
                    native_bounds = list(src.bounds)
                    entry = {
                        "name": path.name,
                        "path": str(path),
                        "crs": src.crs.to_string() if src.crs else None,
                        "extent": native_bounds,
                        "extent_epsg4326": None,
                        "pixel_size_m": abs(src.transform.a),
                        "shape": [src.height, src.width],
                        "nodata": src.nodata,
                    }
                    if src.crs and src.crs.is_defined:
                        try:
                            entry["extent_epsg4326"] = list(
                                transform_bounds(src.crs, "EPSG:4326", *src.bounds)
                            )
                        except Exception:
                            entry["extent_epsg4326"] = None
                    cogs.append(entry)
            except Exception:
                continue
    return {"cogs": cogs}
