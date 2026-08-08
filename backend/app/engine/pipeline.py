"""Viewshed engine pipeline orchestrator.

Connects BBOX calc -> COG crop -> PostGIS query -> DSM build ->
WhiteboxTools viewshed -> directional cone mask.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import rasterio
from pyproj import CRS, Transformer
from shapely.geometry import box
from shapely.ops import transform as shp_transform

from app.engine.cone_filter import create_directional_mask
from app.engine.dsm_builder import (
    build_dsm,
    crop_dem_window,
    fetch_obstacles,
    get_bounding_box,
)
from app.engine.horizon_profiler import (
    compute_horizon_profiles,
    horizon_fraction,
    observer_distance_along_ray,
    ray_azimuths,
)
from app.engine.viewshed import OBSERVER_HEIGHT_DEFAULT, calculate_viewshed

__all__ = ["run_viewshed_pipeline"]

# The bundled Bavarian DEM (DGM) is a Cloud Optimized GeoTIFF in
# ETRS89 / UTM zone 32N. The merged source raster was created without an
# embedded CRS, so we fall back to this when the GeoTIFF declares none.
FALLBACK_CRS_EPSG = 25832


def _resolve_crs(crs) -> CRS:
    """Return ``crs`` if it is a valid pyproj CRS, else the configured fallback."""
    if crs is not None:
        try:
            return CRS.from_user_input(crs)
        except Exception:
            pass
    return CRS.from_epsg(FALLBACK_CRS_EPSG)


def _to_epsg4326(polygon, src_crs):
    transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
    return shp_transform(transformer.transform, polygon)


def run_viewshed_pipeline(
    db_session,
    cog_path: str,
    lat: float,
    lng: float,
    radius_km: float,
    azimuth: float,
    fov: float,
    observer_height: float = OBSERVER_HEIGHT_DEFAULT,
    tree_height: float = 30.0,
    building_height: float = 15.0,
    horizon_enabled: bool = False,
    horizon_max_km: float = 100.0,
    horizon_cache_dir: str | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> dict:
    """Run the full viewshed pipeline and return results.

    Returns a dict with ``visibility`` (cone-masked binary array), ``transform``,
    ``crs``, ``bbox`` and ``observer``.

    If ``progress_callback`` is provided it is invoked at each pipeline stage as
    ``progress_callback(status, progress, step)``.
    """
    def _emit(status: str, progress: int, step: str) -> None:
        if progress_callback is not None:
            progress_callback(status, progress, step)

    _emit("FETCHING_DEM", 10, "Extracting elevation window")
    with rasterio.open(cog_path) as src:
        src_crs = src.crs
        pixel_size = abs(src.transform.a)

    # The COG may lack an embedded CRS (see FALLBACK_CRS_EPSG); resolve it so
    # the transformer and reprojections below never receive an empty CRS.
    src_crs = _resolve_crs(src_crs)

    bbox = get_bounding_box(lat, lng, radius_km, src_crs)
    dem_array, transform, crs = crop_dem_window(cog_path, bbox)
    crs = _resolve_crs(crs)

    # Observer position in the DEM's native CRS.
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    obs_x, obs_y = transformer.transform(lng, lat)

    bbox_polygon = _to_epsg4326(box(*bbox), crs)
    buildings_gdf, forests_gdf = fetch_obstacles(db_session, bbox_polygon)

    _emit("BUILDING_DSM", 30, "Overlaying obstacles")
    dsm = build_dsm(
        dem_array,
        transform,
        buildings_gdf,
        forests_gdf,
        crs=crs,
        tree_height_override=tree_height,
        building_height_override=building_height,
    )

    _emit("COMPUTING_VIEWSHED", 60, "Running WhiteboxTools")
    visibility = calculate_viewshed(dsm, transform, crs, (obs_x, obs_y), observer_height)

    radius_px = radius_km * 1000.0 / pixel_size
    # A 360° panoramic viewshed is a full circle: no directional wedge is
    # applied, so relax the FOV back to 360 to keep the whole radius visible.
    effective_fov = 360.0 if fov >= 360.0 else fov
    cone = create_directional_mask(
        dem_array.shape, transform, obs_x, obs_y, azimuth, effective_fov, radius_px
    )
    masked = np.where(cone, visibility, 0).astype(np.uint8)

    _emit(
        "APPLYING_CONE",
        85,
        "Applying directional mask" if effective_fov < 360.0 else "Applying panoramic mask",
    )

    result = {
        "visibility": masked,
        "transform": transform,
        "crs": crs,
        "bbox": bbox,
        "observer": (obs_x, obs_y),
    }

    # Optional long-range horizon check for the requested direction(s).
    if horizon_enabled:
        _emit("HORIZON", 90, "Checking distant horizon")
        rays = ray_azimuths(azimuth, fov)
        profiles = compute_horizon_profiles(
            cog_path,
            (lat, lng),
            rays,
            max_distance_km=horizon_max_km,
            cache_dir=horizon_cache_dir,
        )
        origin = profiles[rays[0]]
        col, row = ~transform * (obs_x, obs_y)
        row_i = min(max(int(round(row)), 0), dem_array.shape[0] - 1)
        col_i = min(max(int(round(col)), 0), dem_array.shape[1] - 1)
        eye_altitude = float(dem_array[row_i, col_i]) + observer_height
        clear = 0
        for ray_az in rays:
            obs_dist = observer_distance_along_ray(
                ray_az, origin.origin_x, origin.origin_y, obs_x, obs_y
            )
            clear += horizon_fraction(profiles[ray_az], obs_dist, eye_altitude, horizon_max_km)
        horizon_score = clear / len(rays)
        result["horizon_score"] = round(horizon_score, 4)
        result["horizon_pass"] = horizon_score > 0.0

    return result
