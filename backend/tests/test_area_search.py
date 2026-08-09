"""Tests for the multi-point area search engine (Phase 1)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import from_origin

import app.engine.area_search as area
from app.engine.area_search import run_area_search, sample_grid_points, score_viewshed
from shapely.geometry import Point, Polygon

CRS_25832 = CRS.from_epsg(25832)
TRANSFORM = from_origin(500000, 5500200, 10, 10)  # 10m pixels, north-up


def _make_cog(path, size=200):
    arr = np.zeros((size, size), dtype=np.float32)
    with rasterio.open(
        str(path), "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs=CRS_25832, transform=TRANSFORM,
    ) as dst:
        dst.write(arr, 1)


def _square_polygon_wgs84():
    # A 400m x 400m square centred near origin (500300, 5499700) -> lat/lng.
    t = Transformer.from_crs(CRS_25832, "EPSG:4326", always_xy=True)
    (minlng, minlat) = t.transform(500100, 5499500)
    (maxlng, maxlat) = t.transform(500500, 5499900)
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [minlng, minlat],
                [maxlng, minlat],
                [maxlng, maxlat],
                [minlng, maxlat],
                [minlng, minlat],
            ]
        ],
    }


def test_sample_grid_points_inside_polygon():
    poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    pts = sample_grid_points(poly, 25.0)
    # Only strictly-interior cells (25/50/75 in both axes) are kept -> 3x3.
    assert len(pts) == 9
    assert all(poly.contains(Point(p)) for p in pts)


def test_score_viewshed_perfect_and_blocked():
    cone = np.ones((10, 10), dtype=bool)
    assert score_viewshed(np.ones((10, 10), dtype=np.uint8), cone) == 1.0
    assert score_viewshed(np.zeros((10, 10), dtype=np.uint8), cone) == 0.0

    # Half visible cells -> score 0.5
    vis = np.ones((10, 10), dtype=np.uint8)
    vis[5:, :] = 0
    assert score_viewshed(vis, cone) == 0.5


def test_area_search_returns_scored_feature_collection(tmp_path, monkeypatch):
    cog = tmp_path / "cog.tif"
    _make_cog(cog)

    empty_gdf = gpd.GeoDataFrame(geometry=[])
    monkeypatch.setattr(area, "fetch_obstacles", lambda *a, **k: (empty_gdf, empty_gdf))
    monkeypatch.setattr(
        area, "calculate_viewshed",
        lambda dsm, transform, crs, obs, height, **kwargs: np.ones(dsm.shape, dtype=np.uint8),
    )

    fc = run_area_search(
        db_session=None,
        cog_path=str(cog),
        search_area_geojson=_square_polygon_wgs84(),
        radius_km=0.3,
        azimuth=270.0,
        fov=360.0,
        grid_step_m=100.0,
    )

    assert fc["type"] == "FeatureCollection"
    assert fc["meta"]["count"] > 0
    first = fc["features"][0]
    assert first["geometry"]["type"] == "Point"
    assert "score" in first["properties"]
    # Everything visible and full 360° -> every sampled point scores 1.0.
    assert all(f["properties"]["score"] == 1.0 for f in fc["features"])


def test_area_search_writes_dsm_once_and_threads_path(tmp_path, monkeypatch):
    """The shared DSM GeoTIFF must be written exactly once per area search and
    every per-point viewshed call must reuse that same file (no re-serialization).
    """
    cog = tmp_path / "cog.tif"
    _make_cog(cog)

    empty_gdf = gpd.GeoDataFrame(geometry=[])
    monkeypatch.setattr(area, "fetch_obstacles", lambda *a, **k: (empty_gdf, empty_gdf))

    dsm_writes: list[str] = []
    seen_dsm_paths: set[str] = set()
    calls: list[str] = []

    def fake_write_dsm(path, dsm_array, transform, crs):
        dsm_writes.append(str(path))

    def fake_calculate_viewshed(dsm, transform, crs, obs, height, **kwargs):
        calls.append(len(calls))
        seen_dsm_paths.add(kwargs.get("dsm_path"))
        return np.ones(dsm.shape, dtype=np.uint8)

    monkeypatch.setattr(area, "write_dsm", fake_write_dsm)
    monkeypatch.setattr(area, "calculate_viewshed", fake_calculate_viewshed)

    fc = run_area_search(
        db_session=None,
        cog_path=str(cog),
        search_area_geojson=_square_polygon_wgs84(),
        radius_km=0.3,
        azimuth=270.0,
        fov=360.0,
        grid_step_m=100.0,
    )

    # DSM serialized exactly once.
    assert len(dsm_writes) == 1
    # Every per-point viewshed call reused that single dsm_path.
    assert len(calls) > 0
    assert len(seen_dsm_paths) == 1
    assert seen_dsm_paths == {dsm_writes[0]}
    assert fc["meta"]["count"] == len(calls)
