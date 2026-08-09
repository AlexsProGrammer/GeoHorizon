"""Celery tasks for the viewshed pipeline."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import redis
from celery import chord, group
from pyproj import CRS
from rasterio.transform import Affine

from app.core.db import SessionLocal
from app.engine.area_search import (
    prepare_area_search,
    process_points_batch,
    resolve_engine,
)
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
        panoramic_directions=params.get("panoramic_directions", 12),
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
    return _run_area_search_for_task(self.request.id, params)


def _circle_polygon_wgs84(lng: float, lat: float, radius_km: float, num_points: int = 64) -> dict:
    """Build a WGS84 circular GeoJSON polygon centred on ``(lng, lat)``.

    Used by single-point mode so it can reuse the same multi-point area-search
    engine: the clicked observation point becomes the centre of a circular
    search area of the given radius, and nearby grid points are scored as
    candidate viewpoints.
    """
    radius_m = radius_km * 1000.0
    meters_per_deg_lat = 111320.0
    meters_per_deg_lng = 111320.0 * math.cos(math.radians(lat))
    coords = []
    for i in range(num_points):
        angle = 2.0 * math.pi * i / num_points
        dx = math.sin(angle) * radius_m
        dy = math.cos(angle) * radius_m
        coords.append([lng + dx / meters_per_deg_lng, lat + dy / meters_per_deg_lat])
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


@celery_app.task(name="viewshed.merge_area_search")
def merge_area_search_results(
    results: list, task_id: str, dsm_path: str | None, crs_str: str, total: int
) -> dict:
    """Chord callback that merges all area-search batch results and persists them.

    Receives the ordered results from every ``run_area_search_batch_task``,
    merges them in ``batch_index`` order into a single FeatureCollection, writes
    the scored GeoJSON, cleans up the shared DSM and publishes the final SUCCESS
    progress frame. Running this as a dedicated Celery task (in a chord) means the
    orchestrator never calls ``result.get()`` inside a task and never deletes the
    shared DSM before the async batches have loaded it.
    """
    try:
        ordered = sorted(results, key=lambda r: r["batch_index"])
        features: list = []
        for r in ordered:
            features.extend(r["features"])
        fc = {
            "type": "FeatureCollection",
            "features": features,
            "meta": {"crs": crs_str, "count": total},
        }
        _persist_area_result(task_id, fc)
    except Exception as exc:
        _publish_progress(task_id, "FAILURE", 0, f"Area search failed: {exc}")
        raise
    finally:
        if dsm_path:
            try:
                Path(dsm_path).unlink(missing_ok=True)
            except Exception:
                pass

    _publish_progress(task_id, "SUCCESS", 100, "Complete")
    return {
        "result_path": str(PROCESSED_DIR / f"area_{task_id}.json"),
        "count": total,
        "crs": crs_str,
    }


def _run_area_search_for_task(task_id: str, params: dict) -> dict:
    """Core area-search orchestration shared by area-search and point modes.

    Builds the shared DSM and grid, then either dispatches the grid points to
    Celery workers (as a chord with ``merge_area_search_results`` as its
    callback) or processes them serially. Point mode (``viewshed.run_pipeline``)
    feeds this a circular search area auto-generated around the observer.
    """
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

        # Parallel path: dispatch the grid points to Celery workers as a chord.
        # The merge callback finalizes the result (persist, clean up the shared
        # DSM, publish SUCCESS), so this orchestrator never blocks on
        # ``result.get()`` and never deletes the DSM ahead of the async batches
        # (fixes the "Never call result.get() within a task" RuntimeError and the
        # resulting FileNotFoundError when the orchestrator's ``finally`` removed
        # the shared DSM before the batches loaded it).
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
                                "panoramic_directions": ctx["panoramic_directions"],
                                "horizon": horizon_ref,
                                "batch_index": bi,
                                "task_id": task_id,
                                "batch_offset": offset,
                                "global_total": total,
                            }
                        )
                    )
                    offset += len(batch)

                chord(group(headers))(
                    merge_area_search_results.s(
                        task_id=task_id,
                        dsm_path=str(dsm_path),
                        crs_str=crs_str,
                        total=total,
                    )
                )
            except Exception:
                dsm_path.unlink(missing_ok=True)
                raise

            return {
                "task_id": task_id,
                "state": "PROCESSING",
                "count": total,
                "crs": crs_str,
            }

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
                panoramic_directions=ctx["panoramic_directions"],
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
    """Single-point viewshed, unified with the area-search result format.

    The clicked observation point is wrapped in a circular search area of the
    configured radius and the same multi-point engine scores the nearby grid
    points as candidate viewpoints. The output is a scored GeoJSON
    FeatureCollection (green/yellow/red quality bands), identical to area mode —
    instead of the old single PNG overlay. Directional vs 360° scoring is
    controlled by ``fov`` (>= 360 → panoramic).
    """
    task_id = self.request.id
    circle = _circle_polygon_wgs84(
        params["lng"], params["lat"], params["radius_km"]
    )
    area_params = dict(params)
    area_params["search_area"] = circle
    area_params.setdefault("grid_step_m", 50.0)
    return _run_area_search_for_task(task_id, area_params)
