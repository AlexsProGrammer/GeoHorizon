"""Multi-point area search engine.

Finds the best viewing positions inside a search area (circle or polygon).
The DEM window and DSM are built ONCE for the whole area (``prepare_area_search``),
then each sampled grid point is scored by its sky visibility ratio
(``process_points_batch``). The per-point viewshed uses the fast in-memory
NumPy engine by default, with the WhiteboxTools engine available as a fallback.

The prepare / process split is what lets the Celery orchestrator compute the
DSM once and parallelize the scoring of grid points across workers.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable

import numpy as np
import rasterio
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import box
from shapely.geometry import shape as shape_from_geojson
from shapely.ops import transform as shp_transform

from app.engine.cone_filter import create_directional_mask
from app.engine.dsm_builder import (
    build_dsm,
    crop_dem_window,
    fetch_obstacles,
)
from app.engine.horizon_profiler import (
    HorizonProfile,
    compute_horizon_profiles,
    horizon_fraction,
    observer_distance_along_ray,
    ray_azimuths,
)
from app.engine.numpy_viewshed import reference_viewshed
from app.engine.viewshed import OBSERVER_HEIGHT_DEFAULT, calculate_viewshed, write_dsm

__all__ = [
    "sample_grid_points",
    "score_viewshed",
    "score_viewshed_panoramic",
    "prepare_area_search",
    "process_points_batch",
    "run_area_search",
    "resolve_engine",
]

FALLBACK_CRS_EPSG = 25832
DEFAULT_VIEWSHED_ENGINE = "numpy"


def resolve_engine(engine: str | None = None) -> str:
    """Resolve the viewshed engine from an override or the ``VIEWSHED_ENGINE``
    env var (``auto``/``numpy`` prefer the in-memory engine; ``whitebox`` forces
    the WhiteboxTools fallback)."""
    choice = (engine or os.getenv("VIEWSHED_ENGINE", "auto")).strip().lower()
    if choice in ("whitebox", "wbt"):
        return "whitebox"
    return DEFAULT_VIEWSHED_ENGINE


def _resolve_crs(crs) -> CRS:
    """Return ``crs`` if it is a valid pyproj CRS, else the configured fallback."""
    if crs is not None:
        try:
            return CRS.from_user_input(crs)
        except Exception:
            pass
    return CRS.from_epsg(FALLBACK_CRS_EPSG)


def _to_crs(polygon, src_crs):
    """Transform a WGS84 polygon into the DEM's projected CRS."""
    transformer = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
    return shp_transform(transformer.transform, polygon)


def _to_epsg4326(polygon, src_crs):
    """Transform a projected polygon back into WGS84."""
    transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    return shp_transform(transformer.transform, polygon)


def sample_grid_points(search_area, grid_step_m: float) -> list[tuple]:
    """Generate a regular grid of (x, y) points inside the search polygon.

    ``search_area`` must already be in the DEM's projected CRS. Points are
    spaced ``grid_step_m`` apart and only kept when inside the polygon.
    """
    minx, miny, maxx, maxy = search_area.bounds
    if grid_step_m <= 0:
        return []
    xs = np.arange(minx, maxx + grid_step_m * 1e-9, grid_step_m)
    ys = np.arange(miny, maxy + grid_step_m * 1e-9, grid_step_m)
    if xs.size == 0 or ys.size == 0:
        return []
    # Column-major so the ordering matches the previous x-outer/y-inner loop.
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    gx = gx.ravel()
    gy = gy.ravel()
    inside = shapely.contains_xy(search_area, gx, gy)
    return list(zip(gx[inside].tolist(), gy[inside].tolist()))


def score_viewshed(visibility: np.ndarray, cone: np.ndarray) -> float:
    """Sky visibility ratio: visible cells inside the cone / cells in the cone.

    Returns a value in ``[0.0, 1.0]``. A position where every cell in the
    viewing cone is unobstructed scores 1.0; a fully blocked position scores 0.0.
    """
    in_cone = int(np.count_nonzero(cone))
    if in_cone == 0:
        return 0.0
    visible = int(np.count_nonzero((visibility > 0) & cone))
    return visible / in_cone


def score_viewshed_panoramic(
    visibility: np.ndarray,
    transform,
    shape: tuple,
    x: float,
    y: float,
    radius_px: float,
    directions: int = 12,
    geometry: tuple[np.ndarray, np.ndarray] | None = None,
) -> float:
    """Panoramic sky-visibility score using discrete direction sampling.

    Instead of a single full-circle mask (one global ratio), the 360° view is
    split into ``directions`` evenly-spaced directional cones (e.g. 12 cones of
    30° each) and the per-cone sky-visibility ratio is averaged. This is faster
    and numerically more intuitive for "how good is the all-around view": a spot
    that's wide open on one side but fully blocked on another lands in between
    rather than being averaged into one undifferentiated ratio.

    The expensive viewshed is computed exactly once by the caller; the N cone
    masks are cheap ``&``/``count_nonzero`` operations on the shared meshgrid.
    """
    n_dir = max(1, int(directions))
    slice_fov = 360.0 / n_dir
    total = 0.0
    for k in range(n_dir):
        az = k * slice_fov
        cone = create_directional_mask(
            shape, transform, x, y, az, slice_fov, radius_px, geometry=geometry
        )
        total += score_viewshed(visibility, cone)
    return total / n_dir


def _dem_elevation(dem_array: np.ndarray, transform, x: float, y: float) -> float:
    """Sample the DEM (MSL) at a projected point (x, y)."""
    col, row = ~transform * (x, y)
    row_i = min(max(int(round(row)), 0), dem_array.shape[0] - 1)
    col_i = min(max(int(round(col)), 0), dem_array.shape[1] - 1)
    return float(dem_array[row_i, col_i])


def _serialize_profiles(profiles: dict) -> dict:
    out = {}
    for az, prof in profiles.items():
        out[str(az)] = {
            "distance": prof.distance.tolist(),
            "elevation": prof.elevation.tolist(),
        }
    return out


def prepare_area_search(
    db_session,
    cog_path: str,
    search_area_geojson: dict,
    radius_km: float,
    azimuth: float,
    fov: float,
    grid_step_m: float,
    observer_height: float = OBSERVER_HEIGHT_DEFAULT,
    tree_height: float = 30.0,
    building_height: float = 15.0,
    horizon_enabled: bool = False,
    horizon_max_km: float = 100.0,
    horizon_cache_dir: str | None = None,
    panoramic_directions: int = 12,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict:
    """Build the shared DSM and sampling grid once for an area search.

    Returns a context dict consumed by ``process_points_batch``:

    - ``dsm`` / ``dem``: DSM and raw DEM arrays (identical shape)
    - ``transform`` / ``crs`` / ``pixel_size``: georeferencing
    - ``points`` / ``total``: sampled grid points and their count
    - ``radius_px`` / ``mask_fov`` / ``azimuth`` / ``observer_height``
    - ``panoramic_directions``: number of discrete directions for 360° scoring
    - ``horizon``: serialisable horizon data (or ``None``)
    """
    def _emit(status: str, progress: int, step: str) -> None:
        if progress_callback is not None:
            progress_callback(status, progress, step)

    _emit("PREPARING_AREA", 5, "Loading elevation dataset")
    with rasterio.open(cog_path) as src:
        src_crs = src.crs
        pixel_size = abs(src.transform.a)
    src_crs = _resolve_crs(src_crs)

    search_polygon_4326 = shape_from_geojson(search_area_geojson)
    search_polygon = _to_crs(search_polygon_4326, src_crs)

    minx, miny, maxx, maxy = search_polygon.bounds
    half = radius_km * 1000.0
    bbox = (minx - half, miny - half, maxx + half, maxy + half)

    dem_array, transform, crs = crop_dem_window(cog_path, bbox)
    crs = _resolve_crs(crs)

    bbox_polygon = _to_epsg4326(box(*bbox), crs)
    buildings_gdf, forests_gdf = fetch_obstacles(db_session, bbox_polygon)

    _emit("BUILDING_DSM", 15, "Building digital surface model")
    dsm = build_dsm(
        dem_array,
        transform,
        buildings_gdf,
        forests_gdf,
        crs=crs,
        tree_height_override=tree_height,
        building_height_override=building_height,
    )

    points = sample_grid_points(search_polygon, grid_step_m)
    total = len(points)
    if total == 0:
        return {
            "dsm": dsm,
            "dem": dem_array,
            "transform": transform,
            "crs": crs,
            "pixel_size": pixel_size,
            "points": points,
            "total": total,
            "radius_px": 0.0,
            "mask_fov": 360.0,
            "azimuth": azimuth,
            "observer_height": observer_height,
            "panoramic_directions": max(1, int(panoramic_directions)),
            "horizon": None,
        }

    _emit("SAMPLING", 18, f"Sampled {total} grid points")

    radius_px = radius_km * 1000.0 / pixel_size
    panoramic = fov >= 360.0
    mask_fov = 360.0 if panoramic else fov

    horizon = None
    if horizon_enabled:
        _emit("HORIZON", 19, "Casting horizon rays")
        centroid = search_polygon_4326.centroid  # (lng, lat)
        rays = ray_azimuths(azimuth, fov)
        profiles = compute_horizon_profiles(
            cog_path,
            (centroid.y, centroid.x),
            rays,
            max_distance_km=horizon_max_km,
            cache_dir=horizon_cache_dir,
        )
        origin_x = profiles[rays[0]].origin_x
        origin_y = profiles[rays[0]].origin_y
        horizon = {
            "rays": rays,
            "origin_x": origin_x,
            "origin_y": origin_y,
            "max_km": horizon_max_km,
            "profiles": _serialize_profiles(profiles),
        }

    return {
        "dsm": dsm,
        "dem": dem_array,
        "transform": transform,
        "crs": crs,
        "pixel_size": pixel_size,
        "points": points,
        "total": total,
        "radius_px": radius_px,
        "mask_fov": mask_fov,
        "azimuth": azimuth,
        "observer_height": observer_height,
        "panoramic_directions": max(1, int(panoramic_directions)),
        "horizon": horizon,
    }


def _prepare_horizon_profiles(horizon: dict) -> dict[float, HorizonProfile]:
    """Materialize the JSON-serialised horizon profiles into arrays once."""
    ox = horizon["origin_x"]
    oy = horizon["origin_y"]
    prepared: dict[float, HorizonProfile] = {}
    for az in horizon["rays"]:
        p = horizon["profiles"][str(az)]
        prepared[az] = HorizonProfile(
            azimuth=az,
            origin_x=ox,
            origin_y=oy,
            distance=np.asarray(p["distance"], dtype=np.float64),
            elevation=np.asarray(p["elevation"], dtype=np.float64),
        )
    return prepared


def _horizon_multiplier(
    horizon: dict,
    profiles: dict[float, HorizonProfile],
    x: float,
    y: float,
    eye_altitude: float,
) -> float:
    rays = horizon["rays"]
    ox = horizon["origin_x"]
    oy = horizon["origin_y"]
    max_km = horizon["max_km"]
    clear = 0.0
    for az in rays:
        obs_dist = observer_distance_along_ray(az, ox, oy, x, y)
        clear += horizon_fraction(profiles[az], obs_dist, eye_altitude, max_km)
    return clear / len(rays)


def _stencil_windows(
    shape: tuple, radius: int, row: int, col: int
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
    """Matching (dsm_slice, stencil_slice) bounds for an observer pixel.

    Both are clipped to the DSM; ``None`` when the observer lies outside it.
    """
    h, w = shape
    if not (0 <= row < h and 0 <= col < w):
        return None
    r_lo, r_hi = max(0, row - radius), min(h, row + radius + 1)
    c_lo, c_hi = max(0, col - radius), min(w, col + radius + 1)
    top, left = row - radius, col - radius
    return (r_lo, r_hi, c_lo, c_hi), (r_lo - top, r_hi - top, c_lo - left, c_hi - left)


def _score_point_cropped(
    dsm: np.ndarray,
    transform,
    x: float,
    y: float,
    observer_height: float,
    radius: int,
    radius_px: float,
    sector_id: np.ndarray | None,
    sector_totals: np.ndarray | None,
    cone_stencil: np.ndarray | None,
    cone_total: int,
) -> float:
    """Score one observer using only the (2r+1)^2 window it can actually see.

    Denominators are recomputed from the clipped stencil when the window runs
    off the DSM, matching the full-window path where off-map cells were absent
    from both the numerator and the denominator.
    """
    col, row = ~transform * (x, y)
    row_i, col_i = int(round(row)), int(round(col))
    windows = _stencil_windows(dsm.shape, radius, row_i, col_i)
    if windows is None:
        return 0.0
    (r_lo, r_hi, c_lo, c_hi), (sr_lo, sr_hi, sc_lo, sc_hi) = windows

    sub = dsm[r_lo:r_hi, c_lo:c_hi]
    vis = reference_viewshed(
        sub, (row_i - r_lo, col_i - c_lo), observer_height, max_radius_px=radius_px
    )

    if sector_id is not None and sector_totals is not None:
        sectors = sector_id[sr_lo:sr_hi, sc_lo:sc_hi]
        inside = sectors >= 0
        totals = (
            sector_totals
            if sectors.shape == sector_id.shape
            else np.bincount(sectors[inside], minlength=sector_totals.size).astype(np.float64)
        )
        counts = np.bincount(
            sectors[inside & (vis > 0)], minlength=sector_totals.size
        ).astype(np.float64)
        ratios = np.divide(counts, totals, out=np.zeros_like(totals), where=totals > 0)
        return float(ratios.mean())

    if cone_stencil is None:
        return 0.0
    cone = cone_stencil[sr_lo:sr_hi, sc_lo:sc_hi]
    total = cone_total if cone.shape == cone_stencil.shape else int(np.count_nonzero(cone))
    if total == 0:
        return 0.0
    return float(np.count_nonzero((vis > 0) & cone)) / total


def process_points_batch(
    dsm: np.ndarray,
    transform,
    crs,
    points: list[tuple],
    azimuth: float,
    mask_fov: float,
    radius_px: float,
    observer_height: float,
    horizon: dict | None = None,
    engine: str = DEFAULT_VIEWSHED_ENGINE,
    dsm_path: str | None = None,
    panoramic_directions: int = 12,
    dem: np.ndarray | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
    offset: int = 0,
    global_total: int | None = None,
) -> list[dict]:
    """Compute scored GeoJSON Features for a batch of grid points against a shared DSM.

    ``points`` are ``(x, y)`` projected coordinates. ``transform``/``crs``
    describe the DSM's georeferencing. The numpy engine evaluates each observer
    against a cropped ``(2*radius_px+1)^2`` window and scores it with a
    precomputed observer-relative stencil, so no work is spent on cells outside
    the view radius and no per-point trigonometry is needed. The WhiteboxTools
    engine keeps the original full-window path and reuses a pre-written
    ``dsm_path`` GeoTIFF across the batch.

    ``dem`` is the bare terrain (no obstacle heights) used for the observer's
    eye altitude; it falls back to the DSM when not supplied.

    ``progress_callback``, when given together with ``global_total`` and
    ``offset``, reports global progress for the whole area search.
    """
    from app.engine.cone_filter import (
        build_cone_stencil,
        build_sector_stencil,
        precompute_cone_geometry,
    )

    features: list[dict] = []
    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    n = len(points)
    panoramic = mask_fov >= 360.0
    elevation_source = dsm if dem is None else dem
    horizon_profiles = (
        _prepare_horizon_profiles(horizon)
        if horizon is not None and horizon.get("profiles")
        else None
    )

    radius = max(0, int(np.ceil(radius_px)))
    sector_id = sector_totals = cone_stencil = None
    cone_total = 0
    geometry = None
    if engine == "numpy":
        if panoramic:
            sector_id, sector_totals = build_sector_stencil(radius_px, panoramic_directions)
        else:
            cone_stencil, cone_total = build_cone_stencil(radius_px, azimuth, mask_fov)
    else:
        geometry = precompute_cone_geometry(dsm.shape, transform)

    for i, (x, y) in enumerate(points):
        if engine == "numpy":
            score = _score_point_cropped(
                dsm,
                transform,
                x,
                y,
                observer_height,
                radius,
                radius_px,
                sector_id,
                sector_totals,
                cone_stencil,
                cone_total,
            )
        else:
            visibility = calculate_viewshed(
                dsm, transform, crs, (x, y), observer_height, dsm_path=dsm_path
            )
            if panoramic:
                score = score_viewshed_panoramic(
                    visibility,
                    transform,
                    dsm.shape,
                    x,
                    y,
                    radius_px,
                    directions=panoramic_directions,
                    geometry=geometry,
                )
            else:
                cone = create_directional_mask(
                    dsm.shape, transform, x, y, azimuth, mask_fov, radius_px, geometry=geometry
                )
                score = score_viewshed(visibility, cone)

        properties: dict = {"score": 0.0}
        if horizon_profiles is not None:
            eye_altitude = _dem_elevation(elevation_source, transform, x, y) + observer_height
            multiplier = _horizon_multiplier(horizon, horizon_profiles, x, y, eye_altitude)
            score *= multiplier
            # Surfaced so the horizon pass threshold can be tuned from real runs.
            properties["horizon"] = round(multiplier, 4)

        properties["score"] = round(score, 4)
        lng, lat = to_wgs84.transform(x, y)
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "Point", "coordinates": [round(lng, 6), round(lat, 6)]},
            }
        )

        if progress_callback is not None and global_total:
            gi = offset + i + 1
            if gi % 10 == 0 or gi == global_total:
                pct = 20 + int(70 * gi / global_total)
                progress_callback("CALCULATING", pct, f"Point {gi}/{global_total}")

    return features


def run_area_search(
    db_session,
    cog_path: str,
    search_area_geojson: dict,
    radius_km: float,
    azimuth: float,
    fov: float,
    grid_step_m: float,
    observer_height: float = OBSERVER_HEIGHT_DEFAULT,
    tree_height: float = 30.0,
    building_height: float = 15.0,
    horizon_enabled: bool = False,
    horizon_max_km: float = 100.0,
    horizon_cache_dir: str | None = None,
    panoramic_directions: int = 12,
    progress_callback: Callable[[str, int, str], None] | None = None,
    engine: str | None = None,
) -> dict:
    """Run a multi-point area search (serially) and return scored GeoJSON.

    This is the synchronous, single-process reference path: prepare the shared
    DSM and grid, then score every point in one batch. The Celery orchestrator
    in the worker layer uses the same ``prepare_area_search`` /
    ``process_points_batch`` but splits the points across workers.
    """
    engine = resolve_engine(engine)

    ctx = prepare_area_search(
        db_session,
        cog_path,
        search_area_geojson,
        radius_km,
        azimuth,
        fov,
        grid_step_m,
        observer_height=observer_height,
        tree_height=tree_height,
        building_height=building_height,
        horizon_enabled=horizon_enabled,
        horizon_max_km=horizon_max_km,
        horizon_cache_dir=horizon_cache_dir,
        panoramic_directions=panoramic_directions,
        progress_callback=progress_callback,
    )

    total = ctx["total"]
    if total == 0:
        return {
            "type": "FeatureCollection",
            "features": [],
            "meta": {"crs": ctx["crs"].to_string(), "count": 0},
        }

    dsm_path: str | None = None
    tmp_dir: str | None = None
    try:
        if engine == "whitebox":
            # Write the shared DSM GeoTIFF once and reuse it for every point.
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
            dem=ctx["dem"],
            progress_callback=progress_callback,
            offset=0,
            global_total=total,
        )
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {"crs": ctx["crs"].to_string(), "count": total},
    }
