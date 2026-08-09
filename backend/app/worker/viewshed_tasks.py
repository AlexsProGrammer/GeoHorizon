"""Celery tasks for the viewshed pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import rasterio
import redis
from celery import group
from pyproj import CRS
from rasterio.transform import Affine

from app.core.db import SessionLocal
from app.engine.area_search import (
    prepare_area_search,
    process_points_batch,
    resolve_engine,
)
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


def _worker_slot_count() -> int:
    """Best-effort number of Celery worker processes available for batch tasks.

    Prefers the ``WORKER_CONCURRENCY`` env var (which should mirror the
    ``celery --concurrency`` flag), then falls back to the number of workers
    that answer a control ping, then a sensible default.
    """
    env = os.getenv("WORKER_CONCURRENCY")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    try:
        pong = celery_app.control.ping(timeout=1)
        if pong:
            return max(1, len(pong))
    except Exception:
        pass
    return 4


def _split_batches(points: list, n_batches: int):
    """Split ``points`` into ``n_batches`` roughly-equal round-robin groups."""
    n = max(1, min(n_batches, len(points)))
    return [list(points[i::n]) for i in range(n)]


def _horizon_redis_key(task_id: str) -> str:
    return f"area_horizon:{task_id}"


def _store_horizon(horizon: dict | None, task_id: str) -> dict | None:
    """Persist a shared horizon profile set in Redis and return a slim
    ``{"redis_key": ...}`` reference to embed in batch messages.

    The profile arrays (distance/elevation) apply to the whole area search and
    are identical for every batch, so embedding them in each batch's Celery
    message would duplicate them across the broker. Storing once in Redis keeps
    messages small; each batch resolves the reference on the worker. Returns
    ``None`` when there is no horizon to share.
    """
    if not horizon:
        return None
    try:
        redis_client.setex(_horizon_redis_key(task_id), 3600, json.dumps(horizon))
    except Exception:
        return horizon
    return {"redis_key": _horizon_redis_key(task_id)}


def _load_horizon(horizon_ref: dict | None) -> dict | None:
    """Resolve a horizon reference back into the full profile dictionary.

    ``horizon_ref`` is either ``{"redis_key": ...}`` (shared via Redis) or a
    fully-embedded profile dict (small profiles / fallback path).
    """
    if not horizon_ref:
        return None
    key = horizon_ref.get("redis_key")
    if not key:
        return horizon_ref
    try:
        raw = redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


@celery_app.task(bind=True, name="viewshed.run_area_search_batch")
def run_area_search_batch_task(self, params: dict):
    """Score a subset of an area search's grid points against a shared DSM.

    Receives the path to the shared in-memory DSM (as a JSON-free ``.npy`` with
    serialisable georeferencing, so no large arrays cross the broker) plus that
    batch's slice of grid points. Returns ``{"features": [...], "batch_index": n}``
    which the orchestrator merges in order.
    """
    dsm = np.load(params["dsm_path"])
    transform = Affine(*params["transform"])
    crs = CRS.from_user_input(params["crs"])
    horizon = _load_horizon(params.get("horizon"))

    def progress(status: str, pct: int, step: str) -> None:
        _publish_progress(params["task_id"], status, pct, step)

    features = process_points_batch(
        dsm,
        transform,
        crs,
        params["points"],
        azimuth=params["azimuth"],
        mask_fov=params["mask_fov"],
        radius_px=params["radius_px"],
        observer_height=params["observer_height"],
        horizon=horizon,
        engine="numpy",
        progress_callback=progress,
        offset=params.get("batch_offset", 0),
        global_total=params.get("global_total"),
    )
    return {"features": features, "batch_index": params["batch_index"]}


@celery_app.task(bind=True, name="viewshed.run_area_search")
def run_area_search_task(self, params: dict):
    """Orchestrate a multi-point area search and persist the scored GeoJSON.

    The shared DSM and sampling grid are built once (``prepare_area_search``),
    written to a shared ``.npy`` file, then the grid points are split across
    Celery workers (``run_area_search_batch_task``) and merged when all batches
    finish. For a single-process pool it falls back to the serial path.
    """
    task_id = self.request.id

    def progress(status: str, pct: int, step: str) -> None:
        _publish_progress(task_id, status, pct, step)

    progress("STARTED", 5, "Starting area search")

    engine = resolve_engine(params.get("engine"))

    session = SessionLocal()
    try:
        ctx = prepare_area_search(
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

        total = ctx["total"]
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        crs_str = ctx["crs"].to_string() if hasattr(ctx["crs"], "to_string") else str(ctx["crs"])

        if total == 0:
            fc = {"type": "FeatureCollection", "features": [], "meta": {"crs": crs_str, "count": 0}}
            _persist_area_result(task_id, fc)
            progress("SUCCESS", 100, "Complete")
            return {"result_path": str(PROCESSED_DIR / f"area_{task_id}.json"), "count": 0, "crs": crs_str}

        features = []
        slots = _worker_slot_count()

        # Parallel path (reserve one slot for this orchestrator to wait on).
        if engine == "numpy" and slots > 1 and total >= 2:
            dsm_path = PROCESSED_DIR / f"area_{task_id}_dsm.npy"
            try:
                np.save(dsm_path, ctx["dsm"])
                transform_tuple = tuple(ctx["transform"])
                n_batches = min(slots - 1, total)
                batches = _split_batches(ctx["points"], n_batches)

                # Compute the shared horizon profiles once (already done in
                # prepare_area_search at the search-area centroid) and store
                # them in Redis so every batch shares one copy instead of
                # duplicating the profile arrays across the broker.
                horizon_ref = _store_horizon(ctx["horizon"], task_id)

                headers = []
                offset = 0
                for bi, batch in enumerate(batches):
                    headers.append(
                        run_area_search_batch_task.s(
                            {
                                "dsm_path": str(dsm_path),
                                "transform": transform_tuple,
                                "crs": crs_str,
                                "points": batch,
                                "azimuth": ctx["azimuth"],
                                "mask_fov": ctx["mask_fov"],
                                "radius_px": ctx["radius_px"],
                                "observer_height": ctx["observer_height"],
                                "horizon": horizon_ref,
                                "batch_index": bi,
                                "task_id": task_id,
                                "batch_offset": offset,
                                "global_total": total,
                            }
                        )
                    )
                    offset += len(batch)

                job = group(headers).apply_async()
                results = job.get(timeout=max(120, total * 30), propagate=True)
                ordered = sorted(results, key=lambda r: r["batch_index"])
                for r in ordered:
                    features.extend(r["features"])
            finally:
                dsm_path.unlink(missing_ok=True)
        else:
            # Serial fallback (single slot or explicit whitebox engine). Reuse the
            # already-built DSM; for whitebox write it once and share that file.
            dsm_path = None
            tmp_dir = None
            try:
                if engine == "whitebox":
                    import shutil
                    import tempfile
                    from app.engine.viewshed import write_dsm

                    tmp_dir = tempfile.mkdtemp(prefix="area_viewshed_")
                    dsm_path = os.path.join(tmp_dir, "dsm.tif")
                    write_dsm(dsm_path, ctx["dsm"], ctx["transform"], ctx["crs"])

                features = process_points_batch(
                    ctx["dsm"],
                    ctx["transform"],
                    ctx["crs"],
                    ctx["points"],
                    azimuth=ctx["azimuth"],
                    mask_fov=ctx["mask_fov"],
                    radius_px=ctx["radius_px"],
                    observer_height=ctx["observer_height"],
                    horizon=ctx["horizon"],
                    engine=engine,
                    dsm_path=dsm_path,
                    progress_callback=progress,
                    offset=0,
                    global_total=total,
                )
            finally:
                if tmp_dir is not None:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

        fc = {
            "type": "FeatureCollection",
            "features": features,
            "meta": {"crs": crs_str, "count": total},
        }
        _persist_area_result(task_id, fc)

        progress("SUCCESS", 100, "Complete")
        return {
            "result_path": str(PROCESSED_DIR / f"area_{task_id}.json"),
            "count": total,
            "crs": crs_str,
        }
    except Exception as exc:
        progress("FAILURE", 0, f"Area search failed: {exc}")
        raise
    finally:
        session.close()


def _persist_area_result(task_id: str, fc: dict) -> None:
    """Write the scored GeoJSON FeatureCollection for ``task_id`` to disk."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / f"area_{task_id}.json"
    out_path.write_text(json.dumps(fc))


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
