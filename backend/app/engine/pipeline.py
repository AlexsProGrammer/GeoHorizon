"""Viewshed engine pipeline orchestrator.

Connects BBOX calc -> COG crop -> PostGIS query -> DSM build ->
WhiteboxTools viewshed -> directional cone mask.
"""

from __future__ import annotations

import numpy as np
import rasterio
from pyproj import Transformer
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
) -> dict:
    """Run the full viewshed pipeline and return results.

    Returns a dict with ``visibility`` (cone-masked binary array), ``transform``,
    ``crs``, ``bbox`` and ``observer``.
    """
    with rasterio.open(cog_path) as src:
        src_crs = src.crs
        pixel_size = abs(src.transform.a)

    bbox = get_bounding_box(lat, lng, radius_km, src_crs)
    dem_array, transform, crs = crop_dem_window(cog_path, bbox)

    # Observer position in the DEM's native CRS.
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    obs_x, obs_y = transformer.transform(lng, lat)

    bbox_polygon = _to_epsg4326(box(*bbox), crs)
    buildings_gdf, forests_gdf = fetch_obstacles(db_session, bbox_polygon)

    dsm = build_dsm(
        dem_array,
        transform,
        buildings_gdf,
        forests_gdf,
        crs=crs,
        tree_height_override=tree_height,
        building_height_override=building_height,
    )

    visibility = calculate_viewshed(dsm, transform, crs, (obs_x, obs_y), observer_height)

    radius_px = radius_km * 1000.0 / pixel_size
    cone = create_directional_mask(
        dem_array.shape, transform, obs_x, obs_y, azimuth, fov, radius_px
    )
    masked = np.where(cone, visibility, 0).astype(np.uint8)

    return {
        "visibility": masked,
        "transform": transform,
        "crs": crs,
        "bbox": bbox,
        "observer": (obs_x, obs_y),
    }
