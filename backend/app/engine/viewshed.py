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

__all__ = ["calculate_viewshed"]

OBSERVER_HEIGHT_DEFAULT = 1.8


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


def _write_station_shapefile(path: str, observer_coords: tuple, crs) -> None:
    gdf = gpd.GeoDataFrame(
        geometry=[Point(float(observer_coords[0]), float(observer_coords[1]))],
        crs=crs,
    )
    gdf.to_file(path, driver="ESRI Shapefile")


def calculate_viewshed(
    dsm_array: np.ndarray,
    transform,
    crs,
    observer_coords: tuple,
    observer_height_m: float = OBSERVER_HEIGHT_DEFAULT,
) -> np.ndarray:
    """Run WhiteboxTools viewshed and return the binary visibility raster.

    The DSM is written to a temporary GeoTIFF with matching spatial metadata,
    the observer is written as a point shapefile, and the resulting raster
    (1 = visible, 0 = blocked) is read back. Temp files are cleaned up.
    """
    tmp_dir = tempfile.mkdtemp(prefix="viewshed_")
    dem_path = os.path.join(tmp_dir, "dsm_temp.tif")
    stations_path = os.path.join(tmp_dir, "stations.shp")
    out_path = os.path.join(tmp_dir, "viewshed_out.tif")
    try:
        _write_geotiff(dem_path, dsm_array, transform, crs)
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
