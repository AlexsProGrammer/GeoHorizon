"""WhiteboxTools viewshed execution wrapper."""

from __future__ import annotations

import os
import shutil
import tempfile

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import Point
from whitebox import WhiteboxTools

__all__ = [
    "calculate_viewshed",
    "write_dsm",
    "write_stations",
    "OBSERVER_HEIGHT_DEFAULT",
]

OBSERVER_HEIGHT_DEFAULT = 1.8


def write_dsm(path: str, array: np.ndarray, transform, crs) -> None:
    """Write an elevation/DSM array to a single-band GeoTIFF at ``path``.

    Standalone so a shared DSM can be written to disk once and reused by many
    ``calculate_viewshed`` calls that would otherwise re-write it every time.
    """
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


def _write_station_shapefile(path: str, observer_coords: tuple, crs) -> None:
    gdf = gpd.GeoDataFrame(
        geometry=[Point(float(observer_coords[0]), float(observer_coords[1]))],
        crs=crs,
    )
    gdf.to_file(path, driver="ESRI Shapefile")


def write_stations(path: str, stations, crs) -> None:
    """Write many observer points into a single point shapefile (``stations``
    is an iterable of ``(x, y)`` world coordinates). Useful when running a
    batch through a downstream tool once instead of one call per point.
    """
    points = [Point(float(x), float(y)) for x, y in stations]
    gdf = gpd.GeoDataFrame(
        geometry=points,
        crs=crs,
    )
    gdf.to_file(path, driver="ESRI Shapefile")


def calculate_viewshed(
    dsm_array: np.ndarray,
    transform,
    crs,
    observer_coords: tuple,
    observer_height_m: float = OBSERVER_HEIGHT_DEFAULT,
    dsm_path: str | None = None,
) -> np.ndarray:
    """Run WhiteboxTools viewshed and return the binary visibility raster.

    The DSM is written to a temporary GeoTIFF with matching spatial metadata,
    the observer is written as a point shapefile, and the resulting raster
    (1 = visible, 0 = blocked) is read back. Temp files are cleaned up.

    ``dsm_path``: if a pre-written DSM GeoTIFF is supplied, it is used instead
    of re-writing ``dsm_array`` to disk. This lets an area search write the
    shared DSM once and reuse it for every sampled observer, removing N-1
    redundant rasters. When ``dsm_path`` is given, ``dsm_array`` is only needed
    for its shape/dtype metadata (and is ignored for the actual write).
    """
    tmp_dir = tempfile.mkdtemp(prefix="viewshed_")
    stations_path = os.path.join(tmp_dir, "stations.shp")
    out_path = os.path.join(tmp_dir, "viewshed_out.tif")
    try:
        if dsm_path is not None:
            dem_path = dsm_path
        else:
            dem_path = os.path.join(tmp_dir, "dsm_temp.tif")
            write_dsm(dem_path, dsm_array, transform, crs)

        _write_station_shapefile(stations_path, observer_coords, crs)

        wbt = WhiteboxTools()
        wbt.viewshed(
            dem=dem_path,
            stations=stations_path,
            output=out_path,
            height=float(observer_height_m),
        )

        with rasterio.open(out_path) as src:
            visibility = src.read(1)
        return visibility
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
