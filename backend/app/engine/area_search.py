"""Multi-point area search engine.

Finds the best viewing positions inside a search area (circle or polygon).
The DEM window and DSM are built ONCE for the whole area, then a WhiteboxTools
viewshed is run for each sampled grid point and scored by sky visibility ratio.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from shapely.geometry import Point, box
from shapely.geometry import shape as shape_from_geojson
from shapely.ops import transform as shp_transform

from app.engine.cone_filter import create_directional_mask
from app.engine.dsm_builder import (
    build_dsm,
    crop_dem_window,
    fetch_obstacles,
)
from app.engine.horizon_profiler import (
    compute_horizon_profiles,
    horizon_fraction,
    observer_distance_along_ray,
    ray_azimuths,
)
from app.engine.viewshed import OBSERVER_HEIGHT_DEFAULT, calculate_viewshed, write_dsm

__all__ = ["sample_grid_points", "score_viewshed", "run_area_search"]

FALLBACK_CRS_EPSG = 25832


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
    points: list[tuple] = []
    x = minx
    while x <= maxx:
        y = miny
        while y <= maxy:
            if search_area.contains(Point(x, y)):
                points.append((x, y))
            y += grid_step_m
        x += grid_step_m
    return points


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


def _dem_elevation(dem_array: np.ndarray, transform, x: float, y: float) -> float:
    """Sample the DEM (MSL) at a projected point (x, y)."""
    col, row = ~transform * (x, y)
    row_i = min(max(int(round(row)), 0), dem_array.shape[0] - 1)
    col_i = min(max(int(round(col)), 0), dem_array.shape[1] - 1)
    return float(dem_array[row_i, col_i])


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
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict:
    """Run a multi-point area search and return scored GeoJSON.

    The search area (WGS84 GeoJSON polygon) is transformed into the DEM's CRS,
    the DEM window and DSM are built once for the whole area, and each sampled
    grid point is scored by its sky visibility ratio.

    Returns a GeoJSON ``FeatureCollection`` whose features are Points with a
    ``score`` property (0.0-1.0) plus a ``meta`` object with the CRS string.
    """
    def _emit(status: str, progress: int, step: str) -> None:
        if progress_callback is not None:
            progress_callback(status, progress, step)

    _emit("PREPARING_AREA", 5, "Loading elevation dataset")
    with rasterio.open(cog_path) as src:
        src_crs = src.crs
        pixel_size = abs(src.transform.a)
    src_crs = _resolve_crs(src_crs)

    # Search polygon: WGS84 GeoJSON -> DEM projected CRS.
    search_polygon_4326 = shape_from_geojson(search_area_geojson)
    search_polygon = _to_crs(search_polygon_4326, src_crs)

    # Expand the crop window by the viewing radius so line-of-sight can extend
    # beyond the search area boundary.
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
            "type": "FeatureCollection",
            "features": [],
            "meta": {"crs": crs.to_string(), "count": 0},
        }

    _emit("SAMPLING", 18, f"Sampled {total} grid points")

    to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    radius_px = radius_km * 1000.0 / pixel_size
    panoramic = fov >= 360.0
    # For 360° the mask is a full circle (any azimuth gives the same shape).
    mask_fov = 360.0 if panoramic else fov

    # Optional long-range horizon check. Profiles are computed once per
    # direction relative to the search-area centroid and reused for every point.
    horizon_rays: list[float] = []
    horizon_profiles = None
    if horizon_enabled:
        _emit("HORIZON", 19, "Casting horizon rays")
        centroid = search_polygon_4326.centroid  # (lng, lat)
        horizon_rays = ray_azimuths(azimuth, fov)
        horizon_profiles = compute_horizon_profiles(
            cog_path,
            (centroid.y, centroid.x),
            horizon_rays,
            max_distance_km=horizon_max_km,
            cache_dir=horizon_cache_dir,
        )
        origin_x = horizon_profiles[horizon_rays[0]].origin_x
        origin_y = horizon_profiles[horizon_rays[0]].origin_y
    else:
        origin_x = origin_y = 0.0

    # The DSM is identical for every sampled observer: write it to disk once and
    # reuse the file for all viewshed calls instead of re-serializing it N times.
    _shared_tmp = tempfile.mkdtemp(prefix="area_viewshed_")
    dsm_path = os.path.join(_shared_tmp, "dsm.tif")
    try:
        write_dsm(dsm_path, dsm, transform, crs)
    except Exception:
        shutil.rmtree(_shared_tmp, ignore_errors=True)
        raise

    features = []
    try:
        for idx, (x, y) in enumerate(points):
            visibility = calculate_viewshed(
                dsm, transform, crs, (x, y), observer_height, dsm_path=dsm_path
            )
            cone = create_directional_mask(
                dem_array.shape, transform, x, y, azimuth, mask_fov, radius_px
            )
            score = score_viewshed(visibility, cone)

            if horizon_enabled and horizon_profiles is not None:
                eye_altitude = _dem_elevation(dem_array, transform, x, y) + observer_height
                clear_rays = 0
                for ray_az in horizon_rays:
                    obs_dist = observer_distance_along_ray(
                        ray_az, origin_x, origin_y, x, y
                    )
                    clear_rays += horizon_fraction(
                        horizon_profiles[ray_az], obs_dist, eye_altitude, horizon_max_km
                    )
                horizon_score = clear_rays / len(horizon_rays)
                score *= horizon_score

            lng, lat = to_wgs84.transform(x, y)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"score": round(score, 4)},
                    "geometry": {"type": "Point", "coordinates": [round(lng, 6), round(lat, 6)]},
                }
            )
            if (idx + 1) % 10 == 0 or idx + 1 == total:
                pct = 20 + int(70 * (idx + 1) / total)
                _emit("CALCULATING", pct, f"Point {idx + 1}/{total}")
    finally:
        shutil.rmtree(_shared_tmp, ignore_errors=True)

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {"crs": crs.to_string(), "count": total},
    }
