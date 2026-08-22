from __future__ import annotations

import numpy as np

from app.engine.sightlines import cast_sightlines


def _make_result(dem: np.ndarray, *, observer: tuple[float, float], radius_m: float = 80.0):
    transform = __import__("rasterio.transform", fromlist=["from_origin"]).from_origin(
        0.0, dem.shape[0], 1.0, 1.0
    )
    return cast_sightlines(
        dem,
        transform=transform,
        observer=observer,
        observer_height=1.8,
        radius_m=radius_m,
        azimuth=0.0,
        fov=360.0,
        ray_step_deg=1.0,
        sample_step_m=1.0,
    )


def test_flat_plane_has_all_clear_samples():
    dem = np.zeros((101, 101), dtype=np.float32)
    result = _make_result(dem, observer=(50.0, 50.0), radius_m=40.0)

    assert result.stats["blocked_fraction"] == 0.0
    assert result.stats["grazing_fraction"] == 0.0
    assert result.stats["clear_fraction"] > 0.99
    assert result.samples["state"].size > 0


def test_wall_blocks_shadow_behind_it():
    dem = np.zeros((101, 101), dtype=np.float32)
    dem[:, 65:75] = 40.0

    result = _make_result(dem, observer=(50.0, 10.0), radius_m=80.0)

    assert result.stats["blocked_fraction"] > 0.0
    assert result.stats["clear_fraction"] > 0.0
    assert "blocked" in result.samples["state"]
    assert "clear" in result.samples["state"]


def test_isolated_pillar_creates_narrow_blocked_wedge():
    dem = np.zeros((101, 101), dtype=np.float32)
    dem[28:34, 28:34] = 40.0

    result = _make_result(dem, observer=(50.0, 50.0), radius_m=60.0)

    assert result.stats["blocked_fraction"] > 0.0
    assert result.stats["clear_fraction"] > 0.0
    assert result.stats["clear_fraction"] < 1.0


def test_observer_in_raised_cell_is_not_blinded_by_self():
    dem = np.zeros((101, 101), dtype=np.float32)
    dem[50, 50] = 80.0
    dem[50, 60:70] = 30.0

    result = _make_result(dem, observer=(50.0, 50.0), radius_m=30.0)

    assert result.stats["blocked_fraction"] < 1.0
    assert result.stats["clear_fraction"] > 0.0
