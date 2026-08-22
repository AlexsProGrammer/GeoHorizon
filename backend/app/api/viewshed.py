import json
import os
from pathlib import Path

import numpy as np
import rasterio
import redis
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from rasterio.warp import transform, transform_bounds

from app.engine.terrain_tiles import render_terrain_tile
from app.worker import celery_app
from app.worker.viewshed_tasks import run_area_search_task, run_point_sightlines_task, run_viewshed_task

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
    sample_step_m: float | None = None
    display_spacing_m: float | None = None
    grid_step_m: float = 50.0
    horizon_enabled: bool = False
    horizon_max_km: float = 100.0


class PointSightlineRequest(BaseModel):
    cog_path: str
    lat: float
    lng: float
    radius_km: float
    azimuth: float
    fov: float
    observer_height: float = 1.8
    tree_height: float = 30.0
    building_height: float = 15.0
    sample_step_m: float | None = None
    display_spacing_m: float | None = None
    ray_step_deg: float = 0.5
    grazing_margin_m: float = 2.0
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


@router.post("/point")
async def point_sightline(payload: PointSightlineRequest):
    task = run_point_sightlines_task.delay(payload.model_dump())
    return {"task_id": task.id}


@router.post("/start")
async def start(payload: ViewshedRequest):
    task = run_point_sightlines_task.delay(payload.model_dump())
    return {"task_id": task.id}


@router.post("/area-search")
async def area_search(payload: AreaSearchRequest):
    """Dispatch a multi-point area search as a background Celery task."""
    task = run_area_search_task.delay(payload.model_dump())
    return {"task_id": task.id}


@router.get("/result/{task_id}")
async def get_result(task_id: str):
    """Return the result of a viewshed / area task.

    Area search (and the frontend's point mode, which wraps a circle around the
    click) yields a scored GeoJSON FeatureCollection. The single-observer
    pipeline (``POST /viewshed/start``) instead yields overlay metadata pointing
    at ``GET /viewshed/overlay/{task_id}.png``.
    """
    result: AsyncResult = celery_app.AsyncResult(task_id)
    result_path = PROCESSED_DIR / f"area_{task_id}.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    point_path = PROCESSED_DIR / f"point_{task_id}.json"
    if point_path.exists():
        return json.loads(point_path.read_text())
    viewshed_path = PROCESSED_DIR / f"viewshed_{task_id}.json"
    if viewshed_path.exists():
        return json.loads(viewshed_path.read_text())
    if result.state == "FAILURE":
        raise HTTPException(status_code=500, detail=str(result.info))
    # Favour the Celery result payload when the file is missing but available.
    payload = result.result
    if isinstance(payload, dict) and "result_path" in payload:
        p = Path(payload["result_path"])
        if p.exists():
            return json.loads(p.read_text())
    # SUCCESS with no file means the chord orchestrator returned early and the
    # merge callback has not persisted the result yet -> still in progress.
    raise HTTPException(status_code=202, detail="Task not finished yet")


@router.get("/overlay/{task_id}.png")
async def overlay(task_id: str):
    """Return the single-observer visibility overlay as a translucent PNG."""
    path = PROCESSED_DIR / f"viewshed_{task_id}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No overlay for this task")
    return Response(
        content=path.read_bytes(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/area-result/{task_id}")
async def area_result(task_id: str):
    """Backward-compatible alias of ``GET /result/{task_id}``."""
    return await get_result(task_id)


@router.get("/status/{task_id}")
async def status(task_id: str):
    result: AsyncResult = celery_app.AsyncResult(task_id)
    # With the chord-based orchestrator, the parent task returns (state SUCCESS)
    # as soon as the batch tasks are dispatched; the scored result file is only
    # written by the merge callback afterwards. Report SUCCESS to the frontend
    # only once the result file actually exists, so polling doesn't race ahead
    # of the merge and try to read a not-yet-written result.
    persisted = (
        (PROCESSED_DIR / f"area_{task_id}.json").exists()
        or (PROCESSED_DIR / f"point_{task_id}.json").exists()
        or (PROCESSED_DIR / f"viewshed_{task_id}.json").exists()
    )
    if result.state == "SUCCESS" and not persisted:
        return {
            "task_id": task_id,
            "state": "STARTED",
            "result": None,
            "error": None,
        }
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

    # Clean up any persisted result (point/area mode both use area_{task_id}.json).
    out_path = PROCESSED_DIR / f"area_{task_id}.json"
    if out_path.exists():
        out_path.unlink()
    for name in (
        f"area_{task_id}_dsm.npy",
        f"area_{task_id}_dem.npy",
        f"point_{task_id}.json",
        f"viewshed_{task_id}.json",
        f"viewshed_{task_id}.png",
    ):
        scratch = PROCESSED_DIR / name
        if scratch.exists():
            scratch.unlink()

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


@router.get("/elevation")
async def elevation(lng: float, lat: float):
    """Return the absolute elevation (meters above sea level) from the first
    processed COG at the given WGS84 coordinate (``lng``, ``lat``).

    Samples the DEM directly from the COG — independent of MapLibre's terrain
    tile cache on the client — so hover elevation is always correct even after
    panning/zooming (when MapLibre's in-memory DEM tiles may not be loaded yet).
    """
    cogs = sorted(PROCESSED_DIR.glob("*_cog.tif")) if PROCESSED_DIR.is_dir() else []
    if not cogs:
        raise HTTPException(status_code=404, detail="No processed COG available")
    cog = str(cogs[0])
    try:
        with rasterio.open(cog) as src:
            if src.crs and src.crs.is_geographic:
                x, y = (lng, lat)
            else:
                sx, sy = transform("EPSG:4326", src.crs, [lng], [lat])
                x, y = sx[0], sy[0]
            row, col = src.index(x, y)
            h, w = src.height, src.width
            if not (0 <= row < h and 0 <= col < w):
                return {"elevation": None}
            val = float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])
            nodata = src.nodata
    except Exception:
        return {"elevation": None}

    if not np.isfinite(val):
        return {"elevation": None}
    if nodata is not None and val == nodata:
        return {"elevation": None}
    return {"elevation": val}


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
