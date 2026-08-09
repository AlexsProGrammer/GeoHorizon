"""Directional cone filter.

Builds a boolean mask of grid cells that fall within an azimuth/FOV viewing
cone centered on the observer, bounded by a maximum radius.
"""

from __future__ import annotations

import numpy as np

__all__ = ["create_directional_mask", "precompute_cone_geometry"]


def precompute_cone_geometry(
    shape: tuple,
    transform,
) -> tuple[np.ndarray, np.ndarray]:
    """Precompute the view-independent column/row meshgrids for a grid.

    Most of the cone-filter geometry (the pixel coordinate grid in world or
    pixel space) does not depend on the observer or the cone parameters. For a
    large area search this meshgrid is rebuilt for every grid point, which is a
    per-point allocation that dominates runtime. Call this once per DSM and pass
    the result as ``geometry`` to :func:`create_directional_mask`.

    Returns a ``(col_grid, row_grid)`` pair of ``float64`` arrays matching
    ``shape``, containing pixel-edge-centered column/row indices.
    """
    rows = np.arange(shape[0], dtype=np.float64)
    cols = np.arange(shape[1], dtype=np.float64)
    return np.meshgrid(cols + 0.5, rows + 0.5)


def create_directional_mask(
    shape: tuple,
    transform,
    observer_x: float,
    observer_y: float,
    azimuth_deg: float,
    fov_deg: float,
    radius_px: float,
    geometry: tuple[np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """Return a boolean mask where ``True`` = inside the viewing cone.

    Angles are computed in pixel space relative to the observer pixel.
    Azimuth follows the map convention: 0° = North, 90° = East, 270° = West.
    A cell is inside the cone when its (wrapped) angular delta to ``azimuth``
    is <= ``fov/2`` and its distance to the observer is <= ``radius_px``.

    ``geometry`` is an optional precomputed ``(col_grid, row_grid)`` pair from
    :func:`precompute_cone_geometry`; when omitted it is built here. Reuse the
    same ``geometry`` across many observer points to avoid rebuilding it.
    """
    if geometry is not None:
        colc, rowc = geometry
    else:
        colc, rowc = precompute_cone_geometry(shape, transform)

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
