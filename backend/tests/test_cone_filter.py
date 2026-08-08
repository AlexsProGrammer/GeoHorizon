"""Tests for the directional cone filter (Phase 3)."""

from __future__ import annotations

import numpy as np
from rasterio.transform import from_origin

from app.engine.cone_filter import create_directional_mask


# 100x100 grid, 1m pixels, world origin at (0, 100).
TRANSFORM = from_origin(0, 100, 1, 1)
SHAPE = (100, 100)
# Observer at pixel center (col 49.5, row 49.5) -> world (49.5, 50.5).
OBS = (49.5, 50.5)


def test_west_cone_only_marks_western_wedge():
    radius = 40.0
    mask = create_directional_mask(
        SHAPE, TRANSFORM, *OBS, azimuth_deg=270.0, fov_deg=40.0, radius_px=radius
    )
    # Due-west cells at the observer row (row index 49) should be True.
    row = 49
    west_col = 10  # 39.5px west, within radius and 270° bearing
    assert mask[row, west_col]
    # Due-east cell should be False.
    assert not mask[row, 89]
    assert not mask[row, 50]

    # Count of True cells on the west row should be ~radius wide (col 10..49).
    count = int(mask[row].sum())
    assert 40 - 1 <= count <= 40 + 1


def test_outside_radius_is_flagged():
    mask = create_directional_mask(
        SHAPE, TRANSFORM, *OBS, azimuth_deg=270.0, fov_deg=40.0, radius_px=40.0
    )
    # A cell ~44px west of the observer is in the wedge but beyond the radius.
    assert not mask[49, 5]


def test_full_circle_everything_in_radius():
    mask = create_directional_mask(
        SHAPE, TRANSFORM, *OBS, azimuth_deg=0.0, fov_deg=360.0, radius_px=1000.0
    )
    # With a full 360° FOV and a radius covering the grid, every cell is True.
    assert mask.all()
