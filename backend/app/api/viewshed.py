import json
import os
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
import redis
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel
from rasterio.warp import transform_bounds

from app.engine.terrain_tiles import render_terrain_tile
from app.worker import celery_app
from app.worker.viewshed_tasks import run_area_search_task, run_viewshed_task

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
    horizon_enabled: bool = False
    horizon_max_km: float = 100.0


class AreaSearchRequest(BaseModel):
    cog_path: str
    search_area: dict  # GeoJSON Polygon (WGS84)
    radius_km: float
    azimuth: float
    fov: float
    grid_step_m: float = 50.0
    observer_height: float = 1.8
    tree_height: float = 30.0
    building_height: float = 15.0
    horizon_enabled: bool = False
    horizon_max_km: float = 100.0


@router.post("/start")
async def start(payload: ViewshedRequest):
    task = run_viewshed_task.delay(payload.model_dump())
    return {"task_id": task.id}


@router.post("/area-search")
async def area_search(payload: AreaSearchRequest):
    """Dispatch a multi-point area search as a background Celery task."""
    task = run_area_search_task.delay(payload.model_dump())
    return {"task_id": task.id}


@router.get("/area-result/{task_id}")
async def area_result(task_id: str):
    """Return the scored GeoJSON FeatureCollection of an area search task."""
    result: AsyncResult = celery_app.AsyncResult(task_id)
    if result.state == "SUCCESS":
        result_path = PROCESSED_DIR / f"area_{task_id}.json"
        if result_path.exists():
            return json.loads(result_path.read_text())
        # Fall back to the Celery result payload if the file is missing.
        payload = result.result
        if isinstance(payload, dict) and "result_path" in payload:
            return json.loads(Path(payload["result_path"]).read_text())
        return {"type": "FeatureCollection", "features": [], "meta": {"count": 0}}
    if result.state == "FAILURE":
        raise HTTPException(status_code=500, detail=str(result.info))
    raise HTTPException(status_code=202, detail="Task not finished yet")


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


@router.get("/result/{task_id}/image")
async def get_result_image(task_id: str):
    """Return the viewshed result as a PNG image with bounding box metadata.

    Converts the GeoTIFF visibility raster to a colored PNG:
    - Visible cells (1) → semi-transparent green
    - Blocked / outside cone cells (0) → transparent

    The geographical bounds are returned in the ``X-Bounds`` response header
    (EPSG:4326) so the frontend can anchor the image with Deck.gl's BitmapLayer.
    """
    tif_path = PROCESSED_DIR / f"viewshed_{task_id}.tif"
    if not tif_path.exists():
        raise HTTPException(status_code=404, detail="Result not found")

    with rasterio.open(tif_path) as src:
        data = src.read(1)
        if src.crs:
            bbox_4326 = list(transform_bounds(src.crs, "EPSG:4326", *src.bounds))
        else:
            bbox_4326 = list(src.bounds)

    rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    visible_mask = data == 1
    rgba[visible_mask, 0] = 0     # R
    rgba[visible_mask, 1] = 200   # G
    rgba[visible_mask, 2] = 0     # B
    rgba[visible_mask, 3] = 180   # A (semi-transparent)

    img = Image.fromarray(rgba, "RGBA")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={
            "X-Bounds": json.dumps(bbox_4326),
            "X-CRS": "EPSG:4326",
        },
    )


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
                    if src.crs:
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


@router.get("/terrain/{z}/{x}/{y}.png")
async def terrain_tile(z: int, x: int, y: int):
    """Return a Mapbox terrain-RGB PNG tile for MapLibre 3D terrain.

    The tile is warped from the first available ``*_cog.tif`` in the processed
    directory into Web-Mercator and encoded as terrain-RGB. Tiles are cached
    on disk so repeated requests are cheap.
    """
    cogs = sorted(PROCESSED_DIR.glob("*_cog.tif")) if PROCESSED_DIR.is_dir() else []
    if not cogs:
        raise HTTPException(status_code=404, detail="No processed COG available")

    cache_dir = PROCESSED_DIR / "terrain_cache"
    png = render_terrain_tile(str(cogs[0]), x, y, z, cache_dir=str(cache_dir))
    if png is None:
        raise HTTPException(status_code=404, detail="Terrain tile could not be rendered")

    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
