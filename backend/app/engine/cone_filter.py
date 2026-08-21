"""Directional cone filter.

Builds a boolean mask of grid cells that fall within an azimuth/FOV viewing
cone centered on the observer, bounded by a maximum radius.
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "create_directional_mask",
    "precompute_cone_geometry",
    "build_sector_stencil",
    "build_cone_stencil",
]


def _offset_grids(radius_px: float) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    """Observer-relative ``(radius, d_row, d_col, bearing)`` grids.

    Cone geometry depends only on the offset from the observer, never on its
    absolute position, so these can be built once and reused for every point.
    """
    r = max(0, int(np.ceil(radius_px)))
    dy, dx = np.mgrid[-r : r + 1, -r : r + 1].astype(np.float64)
    bearing = np.degrees(np.arctan2(dx, -dy)) % 360.0
    return r, dy, dx, bearing


def build_sector_stencil(
    radius_px: float, directions: int
) -> tuple[np.ndarray, np.ndarray]:
    """Sector-index stencil for panoramic scoring, in observer-relative space.

    Returns ``(sector_id, totals)``: an ``int16`` ``(2r+1, 2r+1)`` array holding
    the sector each cell belongs to (``-1`` outside the radius), and the number
    of cells per sector. Scoring a point then costs one ``bincount`` instead of
    ``directions`` full-grid mask constructions.
    """
    n = max(1, int(directions))
    r, dy, dx, bearing = _offset_grids(radius_px)
    inside = (dx * dx + dy * dy) <= radius_px * radius_px
    sector = (bearing / (360.0 / n)).astype(np.int16)
    np.clip(sector, 0, n - 1, out=sector)
    sector[~inside] = -1
    totals = np.bincount(sector[inside].ravel(), minlength=n).astype(np.float64)
    return sector, totals


def build_cone_stencil(
    radius_px: float, azimuth_deg: float, fov_deg: float
) -> tuple[np.ndarray, int]:
    """Boolean cone stencil in observer-relative space, plus its cell count."""
    r, dy, dx, bearing = _offset_grids(radius_px)
    delta = np.abs(bearing - azimuth_deg % 360.0)
    delta = np.minimum(delta, 360.0 - delta)
    inside = (delta <= fov_deg / 2.0) & (np.hypot(dx, dy) <= radius_px)
    return inside, int(np.count_nonzero(inside))


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
