"""Tests for the viewshed pipeline orchestrator (Phase 5).

Mocks the PostGIS query and WhiteboxTools step to avoid a live DB/binaries.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.crs import CRS

import app.engine.pipeline as pipeline
from app.engine.pipeline import run_viewshed_pipeline

CRS_25832 = CRS.from_epsg(25832)
TRANSFORM = from_origin(500000, 5500200, 1, 1)  # 200x200 @ 1m, north-up


def _make_cog(path):
    arr = np.zeros((200, 200), dtype=np.float32)
    with rasterio.open(
        str(path), "w", driver="GTiff", height=200, width=200, count=1,
        dtype="float32", crs=CRS_25832, transform=TRANSFORM,
    ) as dst:
        dst.write(arr, 1)


def _observer_latlng():
    t = Transformer.from_crs(CRS_25832, "EPSG:4326", always_xy=True)
    return t.transform(500100.0, 5500100.0)  # (lng, lat)


def test_pipeline_returns_masked_visibility(tmp_path, monkeypatch):
    cog = tmp_path / "cog.tif"
    _make_cog(cog)

    empty_gdf = gpd.GeoDataFrame(geometry=[])

    monkeypatch.setattr(pipeline, "fetch_obstacles", lambda *a, **k: (empty_gdf, empty_gdf))
    monkeypatch.setattr(
        pipeline, "calculate_viewshed",
        lambda dsm, transform, crs, obs, height: np.ones(dsm.shape, dtype=np.uint8),
    )

    lng, lat = _observer_latlng()
    result = run_viewshed_pipeline(
        db_session=None,
        cog_path=str(cog),
        lat=lat,
        lng=lng,
        radius_km=0.05,  # 50m, stays inside the 200m COG
        azimuth=90.0,    # east
        fov=40.0,
    )

    vis = result["visibility"]
    assert vis.shape == (100, 100)  # 2*50m = 100m crop
    # Everything is visible; the cone mask keeps only the eastern wedge.
    assert vis.max() == 1
    assert vis.min() == 0
    assert "transform" in result and "crs" in result and "bbox" in result
    # East-west asymmetry: east half has more visible cells than west half.
    assert vis[:, 50:].sum() > vis[:, :50].sum()
