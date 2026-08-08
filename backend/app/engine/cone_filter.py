"""Directional cone filter.

Builds a boolean mask of grid cells that fall within an azimuth/FOV viewing
cone centered on the observer, bounded by a maximum radius.
"""

from __future__ import annotations

import numpy as np

__all__ = ["create_directional_mask"]


def create_directional_mask(
    shape: tuple,
    transform,
    observer_x: float,
    observer_y: float,
    azimuth_deg: float,
    fov_deg: float,
    radius_px: float,
) -> np.ndarray:
    """Return a boolean mask where ``True`` = inside the viewing cone.

    Angles are computed in pixel space relative to the observer pixel.
    Azimuth follows the map convention: 0° = North, 90° = East, 270° = West.
    A cell is inside the cone when its (wrapped) angular delta to ``azimuth``
    is <= ``fov/2`` and its distance to the observer is <= ``radius_px``.
    """
    rows = np.arange(shape[0], dtype=np.float64)
    cols = np.arange(shape[1], dtype=np.float64)
    colc, rowc = np.meshgrid(cols + 0.5, rows + 0.5)

    inv = ~transform
    obs_px, obs_py = inv * (observer_x, observer_y)

    dx = colc - obs_px
    dy = rowc - obs_py
    distance = np.hypot(dx, dy)

    # Bearing clockwise from North (North = -row in pixel space).
    bearing = np.degrees(np.arctan2(dx, -dy)) % 360.0

    center = azimuth_deg % 360.0
    half = fov_deg / 2.0

    delta = np.abs(bearing - center)
    delta = np.minimum(delta, 360.0 - delta)

    return (delta <= half) & (distance <= radius_px)
