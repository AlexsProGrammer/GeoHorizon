"""Visibility raster -> map overlay PNG.

The single-point pipeline produces a binary visibility raster in the DEM's
projected CRS. MapLibre image sources need WGS84 corner coordinates, so the
raster is reprojected to EPSG:4326 and encoded as a translucent RGBA PNG.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject

__all__ = ["visibility_overlay_png", "MAX_OVERLAY_PX"]

# Keeps the encoded overlay small enough to hand to the browser in one request.
MAX_OVERLAY_PX = 2048
VISIBLE_RGBA = (34, 197, 94, 140)


def visibility_overlay_png(
    visibility: np.ndarray, transform, crs
) -> tuple[bytes, list[float]]:
    """Return ``(png_bytes, [west, south, east, north])`` in EPSG:4326.

    Visible cells are painted translucent green; everything else is fully
    transparent so the basemap shows through.
    """
    src = np.ascontiguousarray(visibility, dtype=np.uint8)
    height, width = src.shape
    bounds = array_bounds(height, width, transform)

    dst_transform, dst_w, dst_h = calculate_default_transform(
        crs, "EPSG:4326", width, height, *bounds
    )
    scale = max(dst_w / MAX_OVERLAY_PX, dst_h / MAX_OVERLAY_PX, 1.0)
    if scale > 1.0:
        dst_w = max(1, int(dst_w / scale))
        dst_h = max(1, int(dst_h / scale))
        dst_transform, dst_w, dst_h = calculate_default_transform(
            crs, "EPSG:4326", width, height, *bounds, dst_width=dst_w, dst_height=dst_h
        )

    warped = np.zeros((dst_h, dst_w), dtype=np.uint8)
    reproject(
        source=src,
        destination=warped,
        src_transform=transform,
        src_crs=crs,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        resampling=Resampling.nearest,
    )

    rgba = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
    rgba[warped > 0] = VISIBLE_RGBA

    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)

    west, south, east, north = array_bounds(dst_h, dst_w, dst_transform)
    return buf.getvalue(), [west, south, east, north]
