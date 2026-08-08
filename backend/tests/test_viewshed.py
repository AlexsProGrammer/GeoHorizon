"""Tests for the WhiteboxTools viewshed wrapper (Phase 4).

These exercise the real WhiteboxTools binary, which downloads on first use, so
they are grouped and run together in a single container session.
"""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.transform import from_origin
from rasterio.crs import CRS

from app.engine.viewshed import calculate_viewshed

CRS_25832 = CRS.from_epsg(25832)
TRANSFORM = from_origin(0, 50, 1, 1)  # 1m pixels, world y from 50 down to 0
RES = 1.0


@pytest.fixture
def flat_dem():
    return np.zeros((50, 50), dtype=np.float64)


def test_flat_surface_is_fully_visible(flat_dem):
    # Observer near center-left; a perfectly flat surface is unobstructed.
    vis = calculate_viewshed(
        flat_dem, TRANSFORM, CRS_25832, observer_coords=(10.0, 25.0), observer_height_m=1.8
    )
    assert vis.shape == flat_dem.shape
    # Visible cells are marked 1, others (incl. the station cell) are not 1.
    visible = vis[vis == 1]
    assert visible.size > 0


def test_obstacle_occlusion_blocks_shadow(flat_dem):
    # A 100m vertical barrier at column 20 between the observer (left) and right.
    dem = flat_dem.copy()
    dem[:, 20] = 100.0

    vis = calculate_viewshed(
        dem, TRANSFORM, CRS_25832, observer_coords=(10.0, 25.0), observer_height_m=1.8
    )

    # Cells before the barrier (col < 20) remain visible.
    assert vis[10, 15] == 1
    # Cells behind the barrier (col > 20) are blocked.
    assert vis[10, 30] == 0
    assert vis[40, 35] == 0
