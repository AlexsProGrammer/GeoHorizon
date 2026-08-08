"""Tests for the engine DSM builder (Phase 2)."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.crs import CRS
from shapely.geometry import box

from app.engine.dsm_builder import (
    build_dsm,
    crop_dem_window,
    get_bounding_box,
    FOREST_DEFAULT_HEIGHT,
    BUILDING_DEFAULT_HEIGHT,
)


TEST_CRS = CRS.from_epsg(25832)
RES = 10.0  # meters per pixel


@pytest.fixture
def transform():
    return from_origin(500000, 5500000, RES, RES)


@pytest.fixture
def flat_dem(transform):
    # 100x100 flat DEM @ 0m elevation
    return np.zeros((100, 100), dtype=np.float32)


def test_get_bounding_box_centers_on_observer():
    # Observer at the CRS origin (EPSG:25832)
    x0, y0 = 500000.0, 5500000.0
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    lng, lat = transformer.transform(x0, y0)

    bbox = get_bounding_box(lat, lng, radius_km=1.0, src_crs=TEST_CRS)
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    assert abs(cx - x0) < 0.1
    assert abs(cy - y0) < 0.1
    # 2km side length in meters
    assert abs((bbox[2] - bbox[0]) - 2000.0) < 1.0
    assert abs((bbox[3] - bbox[1]) - 2000.0) < 1.0


def test_crop_dem_window_reads_subset(tmp_path):
    # Write a synthetic COG: 50x50, flat value 42
    path = tmp_path / "dem.tif"
    arr = np.full((50, 50), 42.0, dtype=np.float32)
    tfm = from_origin(500000, 5500000, RES, RES)
    with rasterio.open(
        path, "w", driver="GTiff", height=50, width=50, count=1,
        dtype="float32", crs=TEST_CRS, transform=tfm,
    ) as dst:
        dst.write(arr, 1)

    bbox = (500150.0, 5499850.0, 500250.0, 5499950.0)  # 10x10 window (100m x 100m)
    window, win_tfm, crs = crop_dem_window(str(path), bbox)
    assert window.shape == (10, 10)
    assert np.all(window == 42.0)
    assert crs.to_epsg() == 25832
    assert abs(win_tfm.a - RES) < 1e-6


def test_build_dsm_adds_obstacle_heights(flat_dem, transform):
    # One forest polygon covering the center, one building polygon (in DEM CRS)
    forest_gdf = _gdf([box(500200, 5500200, 500300, 5500300)])
    building_gdf = _gdf([box(500400, 5500400, 500500, 5500500)])

    dsm = build_dsm(flat_dem, transform, building_gdf, forest_gdf, crs=TEST_CRS)

    from rasterio.features import geometry_mask
    forest_mask = ~geometry_mask(
        [box(500200, 5500200, 500300, 5500300)], out_shape=flat_dem.shape, transform=transform
    )
    building_mask = ~geometry_mask(
        [box(500400, 5500400, 500500, 5500500)], out_shape=flat_dem.shape, transform=transform
    )

    assert np.all(dsm[forest_mask] == FOREST_DEFAULT_HEIGHT)
    assert np.all(dsm[building_mask] == BUILDING_DEFAULT_HEIGHT)
    # Outside obstacles the DSM equals the (flat) DEM
    uncovered = ~forest_mask & ~building_mask
    assert np.all(dsm[uncovered] == 0.0)


def test_build_dsm_reprojects_4326_to_dem_crs(flat_dem, transform):
    # Obstacles given in EPSG:4326 should be reprojected into the DEM CRS.
    from pyproj import Transformer
    t = Transformer.from_crs("EPSG:25832", "EPSG:4326", always_xy=True)
    x1, y1 = t.transform(500200, 5500200)
    x2, y2 = t.transform(500300, 5500300)
    forest_gdf = _gdf([box(x1, y1, x2, y2)], crs="EPSG:4326")

    dsm = build_dsm(flat_dem, transform, None, forest_gdf, crs=TEST_CRS)
    from rasterio.features import geometry_mask
    forest_mask = ~geometry_mask(
        [box(500200, 5500200, 500300, 5500300)], out_shape=flat_dem.shape, transform=transform
    )
    assert np.all(dsm[forest_mask] == FOREST_DEFAULT_HEIGHT)


def test_build_dsm_handles_empty_obstacles(flat_dem, transform):
    dsm = build_dsm(flat_dem, transform, None, None, crs=TEST_CRS)
    assert np.all(dsm == 0.0)


def _gdf(polys, crs="EPSG:25832"):
    import geopandas as gpd
    return gpd.GeoDataFrame(geometry=list(polys), crs=crs)
