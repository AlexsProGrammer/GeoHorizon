"""Tests for the in-memory NumPy viewshed engine."""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.crs import CRS
from rasterio.transform import from_origin

from app.engine.numpy_viewshed import numpy_viewshed, numpy_viewshed_multi, reference_viewshed

CRS_25832 = CRS.from_epsg(25832)
TRANSFORM = from_origin(0, 50, 1, 1)  # 1m pixels, world y from 50 down to 0
SHAPE = (50, 50)


def as_world(row: float, col: float) -> tuple[float, float]:
    """World coordinate (x, y) of a pixel centre - observer_coords arg format."""
    return (col, 50.0 - row)


def test_flat_surface_is_fully_visible():
    dem = np.zeros(SHAPE, dtype=np.float64)
    vis = numpy_viewshed(dem, TRANSFORM, CRS_25832, as_world(25.0, 10.0), 1.8)
    assert vis.shape == SHAPE
    # A flat plane viewed from above is unobstructed everywhere.
    assert int((vis == 1).sum()) == SHAPE[0] * SHAPE[1]


def test_obstacle_wall_blocks_shadow():
    dem = np.zeros(SHAPE, dtype=np.float64)
    dem[:, 20] = 100.0  # vertical wall at column 20
    vis = numpy_viewshed(dem, TRANSFORM, CRS_25832, as_world(25.0, 10.0), 1.8)
    # Cells before the wall remain visible.
    assert vis[25, 15] == 1
    # Cells behind the wall are blocked.
    assert vis[25, 30] == 0
    assert vis[40, 35] == 0


def test_point_spike_casts_directional_shadow():
    dem = np.zeros(SHAPE, dtype=np.float64)
    dem[5, 5] = 100.0  # isolated spike NW of the observer
    vis = numpy_viewshed(dem, TRANSFORM, CRS_25832, as_world(25.0, 25.0), 1.8)
    # Cell collinear behind the spike is blocked.
    assert vis[0, 0] == 0
    # Cells perpendicular to the spike remain visible.
    assert vis[25, 5] == 1
    assert vis[45, 25] == 1


def test_observer_outside_window_returns_zeros():
    dem = np.zeros(SHAPE, dtype=np.float64)
    # Observer far outside the grid.
    vis = numpy_viewshed(dem, TRANSFORM, CRS_25832, as_world(1000.0, 1000.0), 1.8)
    assert vis.shape == SHAPE
    assert int((vis == 1).sum()) == 0


def test_multi_returns_stacked_shape():
    dem = np.zeros(SHAPE, dtype=np.float64)
    dem[:, 20] = 100.0
    stations = [as_world(25.0, 10.0), as_world(25.0, 30.0)]
    out = numpy_viewshed_multi(dem, TRANSFORM, CRS_25832, stations, 1.8)
    assert out.shape == (2, *SHAPE)
    assert set(np.unique(out)).issubset({0, 1})
    # Same result as the single-observer call.
    single = numpy_viewshed(dem, TRANSFORM, CRS_25832, stations[0], 1.8)
    assert np.array_equal(out[0], single)


def test_reference_viewshed_flat_direct():
    dem = np.zeros(SHAPE, dtype=np.float64)
    vis = reference_viewshed(dem, (25.0, 10.0), 1.8)
    assert int((vis == 1).sum()) == SHAPE[0] * SHAPE[1]


@pytest.mark.external
def test_numpy_matches_whitebox():
    """Cross-check against WhiteboxTools on a synthetic terrain.

    WhiteboxTools downloads on first use (like test_viewshed.py), so this is
    grouped and only runs in the container session.
    """
    from app.engine.viewshed import calculate_viewshed

    rng = np.random.default_rng(7)
    dem = rng.random(SHAPE) * 60.0
    dem += np.arange(SHAPE[0])[:, None] * 1.5
    dem[10, 10] = 300.0
    dem[15, 15:30] = 150.0

    obs = as_world(25.0, 25.0)
    eye = float(dem[25, 25]) + 1.8

    numpy_vis = numpy_viewshed(dem, TRANSFORM, CRS_25832, obs, 1.8)
    wbt_vis = calculate_viewshed(dem, TRANSFORM, CRS_25832, obs, 1.8)

    # Normalise WBT's marker (its station cell may be 2) to binary visible.
    wbt_bin = (wbt_vis > 0).astype(np.uint8)
    agreement = float((numpy_vis == wbt_bin).mean())
    assert agreement >= 0.95, f"viewshed agreement only {agreement:.3f}"