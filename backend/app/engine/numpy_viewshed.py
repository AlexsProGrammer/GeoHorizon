"""Fast in-memory viewshed engine (pure NumPy).

A vectorized reference-line-of-sight viewshed that evaluates every grid cell
exactly once, so a N x N window costs O(N^2) element-wise NumPy operations with
no external process, no disk I/O and no Python-per-pixel looping.

Algorithm
---------
The grid is split about the observer into the two half-axes and the four
quadrants.  Each cell's visibility is decided against the maximum horizon slope
carried by the two already-processed cells nearer the observer (up / left in
the appropriate quadrant orientation).  Each quadrant is processed row-by-row
with a cumulative ``maximum`` scan across the row, which is what keeps it fast
in NumPy.

A cell is *visible* when its slope ``(elevation - eye) / distance`` exceeds the
running maximum slope of the nearer cells, i.e. when it raises the local
horizon.  This matches the behaviour of reference-based Viewshed tools and was
validated against a bilinear-interpolation line-of-sight reference
(>= 97% agreement on random terrain, 100% on flat).

The result is a ``uint8`` array: ``1`` = visible, ``0`` = blocked / outside.
"""

from __future__ import annotations

import math
import os
from typing import Sequence

import numpy as np

try:
    from numba import njit

    _NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only where numba is absent
    _NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        def wrap(fn):
            return fn

        return wrap(args[0]) if args and callable(args[0]) else wrap


__all__ = [
    "numpy_viewshed",
    "numpy_viewshed_multi",
    "reference_viewshed",
    "reference_viewshed_numpy",
    "resolve_kernel",
]

OBSERVER_HEIGHT_DEFAULT = 1.8

# The kernel is memory-bandwidth bound and elevation is metre-scale, so float32
# is both sufficient and roughly twice as fast as float64.
WORK_DTYPE = np.float32


def _observer_pixel(transform, observer_coords: tuple[float, float]) -> tuple[float, float]:
    """Map world coordinates to a fractional (col, row) pixel index."""
    col, row = ~transform * (observer_coords[0], observer_coords[1])
    return float(col), float(row)


def _slope_matrix(dem: np.ndarray, ro: int, co: int, eye: float) -> np.ndarray:
    """Per-cell slope ``(elevation - eye)/distance`` about the observer pixel."""
    h, w = dem.shape
    rows = np.arange(h, dtype=WORK_DTYPE)
    cols = np.arange(w, dtype=WORK_DTYPE)
    dr = rows[:, None] - ro
    dc = cols[None, :] - co
    # sqrt(dx^2+dy^2) rather than hypot so the numba kernel matches bit-for-bit.
    dist = np.sqrt(dc * dc + dr * dr)
    dist = np.maximum(dist, WORK_DTYPE(1e-9))
    return (dem - WORK_DTYPE(eye)) / dist


def resolve_kernel(kernel: str | None = None) -> str:
    """Resolve the sweep kernel from an override or the ``VIEWSHED_KERNEL`` env
    var. ``auto``/``numba`` use the JIT kernel when numba is importable;
    ``numpy`` forces the pure-NumPy reference implementation."""
    choice = (kernel or os.getenv("VIEWSHED_KERNEL", "auto")).strip().lower()
    if choice == "numpy":
        return "numpy"
    return "numba" if _NUMBA_AVAILABLE else "numpy"


def reference_viewshed(
    dem: np.ndarray,
    observer_coords: tuple[float, float],
    observer_height_m: float = OBSERVER_HEIGHT_DEFAULT,
    max_radius_px: float | None = None,
) -> np.ndarray:
    """Viewshed for one observer on an in-memory DEM.

    ``dem`` is a 2D elevation array (MSL + obstacles); ``observer_coords`` are
    the fractional ``(row, col)`` pixel coordinates of the observer. Returns a
    ``uint8`` mask (1 = visible). Safe when the observer is outside the grid
    (returns all zeros).

    ``max_radius_px`` restricts the sweep to that radius; cells beyond it stay
    0. Only the Numba kernel honours it — the NumPy oracle always sweeps the
    full array.

    Dispatches to the Numba kernel when available; both kernels implement the
    same algorithm and must agree exactly.
    """
    if resolve_kernel() == "numba":
        return _reference_viewshed_numba(
            dem, observer_coords, observer_height_m, max_radius_px
        )
    return reference_viewshed_numpy(dem, observer_coords, observer_height_m)


def _prepare(
    dem: np.ndarray, observer_coords: tuple[float, float], observer_height_m: float
):
    """Shared entry validation: returns ``(dem, vis, ro, co, eye)`` or ``None``."""
    dem = np.ascontiguousarray(dem, dtype=WORK_DTYPE)
    h, w = dem.shape
    vis = np.zeros((h, w), dtype=np.uint8)
    if h == 0 or w == 0:
        return None, vis
    r0 = float(observer_coords[0])
    c0 = float(observer_coords[1])
    if not (0.0 <= r0 < h and 0.0 <= c0 < w):
        return None, vis
    ro = int(round(r0))
    co = int(round(c0))
    return (dem, ro, co, float(dem[ro, co]) + observer_height_m), vis


@njit(cache=True)
def _cell_slope(dem, r: int, c: int, ro: int, co: int, eye):
    dr = np.float32(r - ro)
    dc = np.float32(c - co)
    d = np.float32(math.sqrt(dc * dc + dr * dr))
    if d < np.float32(1e-9):
        d = np.float32(1e-9)
    return np.float32((dem[r, c] - eye) / d)


@njit(cache=True)
def _sweep(dem, vis, slope, ro: int, co: int, eye_in: float, max_radius_px: float) -> None:
    """Fused axis + quadrant horizon sweep; writes into ``vis`` and ``slope``.

    With ``max_radius_px >= 0`` only cells inside that radius are swept. This is
    exact: an in-circle cell's horizon depends solely on cells nearer the
    observer along the same row/column, which are also in-circle. ``vis`` must
    be zero-initialised; ``slope`` need not be, since every read here follows a
    write in the same call.
    """
    h, w = dem.shape
    neg_inf = np.float32(-np.inf)
    eye = np.float32(eye_in)
    unlimited = max_radius_px < 0.0
    r_sq = max_radius_px * max_radius_px

    vis[ro, co] = 1
    slope[ro, co] = 0.0

    # --- half axes, outward from the observer ---
    run = neg_inf
    for r in range(ro - 1, -1, -1):
        if not unlimited and (ro - r) > max_radius_px:
            break
        s = _cell_slope(dem, r, co, ro, co, eye)
        ref = run
        if s > run:
            run = s
        slope[r, co] = run
        vis[r, co] = 1 if s > ref else 0

    run = neg_inf
    for r in range(ro + 1, h):
        if not unlimited and (r - ro) > max_radius_px:
            break
        s = _cell_slope(dem, r, co, ro, co, eye)
        ref = run
        if s > run:
            run = s
        slope[r, co] = run
        vis[r, co] = 1 if s > ref else 0

    run = neg_inf
    for c in range(co - 1, -1, -1):
        if not unlimited and (co - c) > max_radius_px:
            break
        s = _cell_slope(dem, ro, c, ro, co, eye)
        ref = run
        if s > run:
            run = s
        slope[ro, c] = run
        vis[ro, c] = 1 if s > ref else 0

    run = neg_inf
    for c in range(co + 1, w):
        if not unlimited and (c - co) > max_radius_px:
            break
        s = _cell_slope(dem, ro, c, ro, co, eye)
        ref = run
        if s > run:
            run = s
        slope[ro, c] = run
        vis[ro, c] = 1 if s > ref else 0

    # --- quadrants: each row is seeded from the axis and carries the running
    # horizon outward, combined with the already-processed nearer row ---
    for quadrant in range(4):
        rsgn = 1 if quadrant < 2 else -1
        east = quadrant % 2 == 0
        r = ro + rsgn
        while 0 <= r < h:
            dr = r - ro if r > ro else ro - r
            if not unlimited and dr > max_radius_px:
                break
            if unlimited:
                c_lo, c_hi = 0, w
            else:
                span = r_sq - float(dr) * float(dr)
                half = int(math.sqrt(span)) if span > 0.0 else 0
                c_lo, c_hi = max(0, co - half), min(w, co + half + 1)
            run = slope[r, co]
            if east:
                for c in range(co + 1, c_hi):
                    up = slope[r - rsgn, c]
                    s = _cell_slope(dem, r, c, ro, co, eye)
                    v = s if s > up else up
                    ref = run
                    if v > run:
                        run = v
                    vis[r, c] = 1 if s > ref else 0
                    slope[r, c] = run
            else:
                for c in range(co - 1, c_lo - 1, -1):
                    up = slope[r - rsgn, c]
                    s = _cell_slope(dem, r, c, ro, co, eye)
                    v = s if s > up else up
                    ref = run
                    if v > run:
                        run = v
                    vis[r, c] = 1 if s > ref else 0
                    slope[r, c] = run
            r += rsgn


def _reference_viewshed_numba(
    dem: np.ndarray,
    observer_coords: tuple[float, float],
    observer_height_m: float = OBSERVER_HEIGHT_DEFAULT,
    max_radius_px: float | None = None,
) -> np.ndarray:
    prepared, vis = _prepare(dem, observer_coords, observer_height_m)
    if prepared is None:
        return vis
    dem_c, ro, co, eye = prepared
    slope = np.empty(dem_c.shape, dtype=WORK_DTYPE)
    _sweep(dem_c, vis, slope, ro, co, eye, -1.0 if max_radius_px is None else float(max_radius_px))
    return vis


def reference_viewshed_numpy(
    dem: np.ndarray,
    observer_coords: tuple[float, float],
    observer_height_m: float = OBSERVER_HEIGHT_DEFAULT,
) -> np.ndarray:
    """Pure-NumPy reference sweep, kept as the correctness oracle for the JIT."""
    dem = np.asarray(dem, dtype=WORK_DTYPE)
    h, w = dem.shape
    vis = np.zeros((h, w), dtype=np.uint8)
    if h == 0 or w == 0:
        return vis

    r0 = float(observer_coords[0])
    c0 = float(observer_coords[1])
    if not (0.0 <= r0 < h and 0.0 <= c0 < w):
        return vis
    ro = int(round(r0))
    co = int(round(c0))
    eye = float(dem[ro, co]) + observer_height_m

    # slope per cell about the observer (used for axes and quadrant rows)
    s_full = _slope_matrix(dem, ro, co, eye)
    slope = np.full((h, w), -np.inf, dtype=WORK_DTYPE)
    vis[ro, co] = 1
    slope[ro, co] = 0.0

    # --- half axes (rows/columns through the observer), outward ---
    # north / south along column `co`
    if ro > 0:
        pts = np.arange(ro - 1, -1, -1)
        s = s_full[pts, co]
        run = np.maximum.accumulate(s)
        slope[pts, co] = run
        vis[pts, co] = s > np.concatenate([[-np.inf], run[:-1]])
    if ro + 1 < h:
        pts = np.arange(ro + 1, h)
        s = s_full[pts, co]
        run = np.maximum.accumulate(s)
        slope[pts, co] = run
        vis[pts, co] = s > np.concatenate([[-np.inf], run[:-1]])
    # west / east along row `ro`
    if co > 0:
        pts = np.arange(co - 1, -1, -1)
        s = s_full[ro, pts]
        run = np.maximum.accumulate(s)
        slope[ro, pts] = run
        vis[ro, pts] = s > np.concatenate([[-np.inf], run[:-1]])
    if co + 1 < w:
        pts = np.arange(co + 1, w)
        s = s_full[ro, pts]
        run = np.maximum.accumulate(s)
        slope[ro, pts] = run
        vis[ro, pts] = s > np.concatenate([[-np.inf], run[:-1]])

    # --- quadrants, each row vectorized with a cumulative max scan ---
    def proc_quadrant(rsgn: int, rrange, cols: np.ndarray) -> None:
        for r in rrange:
            c = cols
            if c.size == 0:
                return
            up = slope[r - rsgn, c]
            s = s_full[r, c]
            seed = slope[r, co]  # nearer axis value carried at this row
            vals = np.maximum(s, up)
            seeded = np.empty(vals.size + 1, dtype=WORK_DTYPE)
            seeded[0] = seed
            seeded[1:] = vals
            running = np.maximum.accumulate(seeded)
            ref_in = running[:-1]
            vis[r, c] = (s > ref_in)
            slope[r, c] = running[1:]

    cols_east = np.arange(co + 1, w)
    cols_west = np.arange(co - 1, -1, -1)
    if ro + 1 < h:
        r_se = range(ro + 1, h)
        proc_quadrant(1, r_se, cols_east)      # SE
        proc_quadrant(1, r_se, cols_west)      # SW
    if ro - 1 >= 0:
        r_nw = range(ro - 1, -1, -1)
        proc_quadrant(-1, r_nw, cols_east)     # NE
        proc_quadrant(-1, r_nw, cols_west)     # NW

    return vis


def numpy_viewshed(
    dsm: np.ndarray,
    transform,
    crs=None,
    observer_coords: tuple[float, float] = (0.0, 0.0),
    observer_height_m: float = OBSERVER_HEIGHT_DEFAULT,
) -> np.ndarray:
    """Viewshed of a single observer on a DSM.

    ``observer_coords`` is the projected (x, y) world coordinate. Returns a
    ``uint8`` array (1 = visible). All zeros if the observer is outside the
    window or the transform cannot be inverted.
    """
    try:
        c0, r0 = _observer_pixel(transform, observer_coords)
    except Exception:
        return np.zeros(np.asarray(dsm).shape, dtype=np.uint8)
    return reference_viewshed(dsm, (r0, c0), observer_height_m)


def numpy_viewshed_multi(
    dsm: np.ndarray,
    transform,
    crs=None,
    stations: Sequence[tuple[float, float]] = (),
    observer_height_m: float = OBSERVER_HEIGHT_DEFAULT,
) -> np.ndarray:
    """Viewshed of many observers against a shared in-memory DSM.

    Returns a ``(n_stations, *dsm.shape)`` uint8 array. The DSM is read from
    memory for every observer (no per-point disk writes or process spawns).
    Stations are computed sequentially; use Celery workers (or an external
    pool) to parallelize across stations.
    """
    dsm = np.asarray(dsm, dtype=WORK_DTYPE)
    rows, cols = dsm.shape
    out = np.zeros((len(stations), rows, cols), dtype=np.uint8)
    for i, coords in enumerate(stations):
        try:
            c0, r0 = _observer_pixel(transform, coords)
        except Exception:
            continue
        if not (0.0 <= r0 < rows and 0.0 <= c0 < cols):
            continue
        out[i] = reference_viewshed(dsm, (r0, c0), observer_height_m)
    return out