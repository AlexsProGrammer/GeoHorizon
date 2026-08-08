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

    return {
        "visibility": masked,
        "transform": transform,
        "crs": crs,
        "bbox": bbox,
        "observer": (obs_x, obs_y),
    }
