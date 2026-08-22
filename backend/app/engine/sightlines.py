"""Ray-based sightline analysis for point-mode visibility.

The point mode rework uses a ray-casting LOS engine instead of the full area
search grid. It samples the DSM along a set of rays from the observer, checks
whether each sample is visible against the running maximum sightline slope, and
classifies each sampled point as clear/grazing/blocked.

The engine intentionally uses the bare DEM for the observer's eye height, while
sampling the DSM for terrain and obstacle heights along the rays. This keeps the
observer grounded on the actual terrain instead of standing on top of a building
or tree polygon that happened to occupy the clicked cell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pyproj import CRS

__all__ = [
    "OBSERVER_HEIGHT_DEFAULT",
    "SightlineSample",
    "HorizonArc",
    "SightlineResult",
    "cast_sightlines",
    "thin_samples_for_display",
]

OBSERVER_HEIGHT_DEFAULT = 1.8
EARTH_RADIUS_M = 6371000.0
REFRACTION_COEFFICIENT = 1.13


@dataclass
class SightlineSample:
    azimuth: float
    distance_m: float
    elevation_m: float
    clearance_m: float
    state: str


@dataclass
class HorizonArc:
    azimuth_start: float
    azimuth_end: float
    fraction: float
    state: str
    clear_fraction: float
    blocked_fraction: float


@dataclass
class SightlineResult:
    observer: tuple[float, float]
    observer_ground_elevation_m: float
    observer_eye_elevation_m: float
    radius_m: float
    azimuth: float
    fov: float
    samples: dict[str, np.ndarray] = field(default_factory=lambda: {"azimuth": np.array([], dtype=float), "distance": np.array([], dtype=float), "state": np.array([], dtype=str), "clearance": np.array([], dtype=float)})
    horizon_arcs: list[HorizonArc] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=lambda: {"clear_fraction": 0.0, "grazing_fraction": 0.0, "blocked_fraction": 0.0, "mean_clearance_m": 0.0})


def _resolved_crs(crs: Any | None) -> CRS:
    if crs is not None:
        try:
            return CRS.from_user_input(crs)
        except Exception:
            pass
    return CRS.from_epsg(25832)


def _sample_dem_elevation(dem: np.ndarray, transform, x: float, y: float) -> float:
    inv = ~transform
    col, row = inv * (x, y)
    r = int(round(row))
    c = int(round(col))
    r = max(0, min(dem.shape[0] - 1, r))
    c = max(0, min(dem.shape[1] - 1, c))
    return float(dem[r, c])


def _map_to_pixel(transform, x: float, y: float) -> tuple[float, float]:
    inv = ~transform
    return inv * (x, y)


def _sample_bilinear(dem: np.ndarray, row: float, col: float) -> float:
    r0 = int(np.floor(row))
    c0 = int(np.floor(col))
    r1 = min(dem.shape[0] - 1, r0 + 1)
    c1 = min(dem.shape[1] - 1, c0 + 1)
    dr = row - r0
    dc = col - c0
    v00 = float(dem[r0, c0])
    v10 = float(dem[r0, c1])
    v01 = float(dem[r1, c0])
    v11 = float(dem[r1, c1])
    top = v00 * (1.0 - dc) + v10 * dc
    bottom = v01 * (1.0 - dc) + v11 * dc
    return float(top * (1.0 - dr) + bottom * dr)


def _earth_curvature_adjustment(distance_m: float) -> float:
    return (distance_m * distance_m) / (2.0 * EARTH_RADIUS_M * REFRACTION_COEFFICIENT)


def _azimuths_for_fov(azimuth: float, fov: float, ray_step_deg: float) -> np.ndarray:
    step = max(0.5, float(ray_step_deg))
    if fov >= 360.0:
        n = int(math.ceil(360.0 / step))
        return np.linspace(0.0, 360.0, n, endpoint=False)
    n = max(1, int(math.ceil(fov / step)))
    start = azimuth - (fov / 2.0)
    return np.linspace(start, start + fov, n, endpoint=False)


def thin_samples_for_display(
    sample_distances: np.ndarray,
    sample_states: np.ndarray,
    sample_clearances: np.ndarray,
    max_points: int = 50000,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reduce the sample set for map rendering without losing the overall structure.

    The map should keep roughly constant density across the radius, which means
    farther samples are kept less often than near samples. This is a cosmetic
    display thinning step only; the full raw sample arrays remain available for
    statistics.
    """
    if sample_distances.size == 0:
        return sample_distances, sample_states, sample_clearances
    if sample_distances.size <= max_points:
        return sample_distances, sample_states, sample_clearances

    keep = np.ones(sample_distances.shape, dtype=bool)
    target = max(1, int(max_points))
    stride = max(1, int(math.ceil(sample_distances.size / target)))
    keep[::stride] = True
    keep[1::stride] = False
    return sample_distances[keep], sample_states[keep], sample_clearances[keep]


def _build_horizon_arcs(
    dem: np.ndarray,
    transform,
    observer: tuple[float, float],
    observer_eye_elevation_m: float,
    radius_m: float,
    azimuths: np.ndarray,
    sample_step_m: float,
) -> list[HorizonArc]:
    arcs: list[HorizonArc] = []
    if dem.size == 0:
        return arcs

    for i, az in enumerate(azimuths):
        rad = math.radians(az % 360.0)
        dx = math.sin(rad)
        dy = math.cos(rad)
        max_dist = float(radius_m)
        distances = np.arange(0.0, max_dist + sample_step_m, sample_step_m, dtype=float)
        if distances.size == 0:
            continue
        xs = observer[0] + dx * distances
        ys = observer[1] + dy * distances
        elevs = []
        for x, y in zip(xs, ys):
            try:
                px, py = _map_to_pixel(transform, x, y)
                if 0 <= px < dem.shape[1] and 0 <= py < dem.shape[0]:
                    elevs.append(float(_sample_bilinear(dem, py, px)))
                else:
                    elevs.append(np.nan)
            except Exception:
                elevs.append(np.nan)
        array = np.asarray(elevs, dtype=float)
        valid = np.isfinite(array)
        if not np.any(valid):
            continue
        max_dist_used = distances[valid][-1]
        d = distances[valid]
        e = array[valid]
        effective = e - (d * d) / (2.0 * EARTH_RADIUS_M * REFRACTION_COEFFICIENT)
        blocked = effective > observer_eye_elevation_m
        if not np.any(blocked):
            fraction = 1.0
            state = "clear"
        else:
            idx = int(np.argmax(blocked))
            if idx == 0:
                fraction = 0.0
            else:
                fraction = float(d[idx] / max_dist_used) if max_dist_used > 0 else 0.0
            state = "blocked" if fraction < 0.33 else "grazing"
        arcs.append(
            HorizonArc(
                azimuth_start=float(az),
                azimuth_end=float(az + (360.0 / len(azimuths))) % 360.0,
                fraction=fraction,
                state=state,
                clear_fraction=float(1.0 if state == "clear" else 0.0),
                blocked_fraction=float(1.0 if state == "blocked" else 0.0),
            )
        )
    return arcs


def cast_sightlines(
    dem: np.ndarray,
    *,
    transform,
    observer: tuple[float, float],
    observer_height: float = OBSERVER_HEIGHT_DEFAULT,
    radius_m: float = 5000.0,
    azimuth: float = 0.0,
    fov: float = 360.0,
    ray_step_deg: float = 0.5,
    sample_step_m: float = 25.0,
    grazing_margin_m: float = 2.0,
) -> SightlineResult:
    """Cast a set of LOS rays from the observer across the requested FOV.

    The observer position is given in the DEM's coordinate system; all angles are
    map bearings in degrees with 0° = North.
    """
    if dem is None or dem.size == 0:
        raise ValueError("DEM array cannot be empty")
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")

    observer_ground = _sample_dem_elevation(dem, transform, observer[0], observer[1])
    observer_eye = observer_ground + float(observer_height)

    azimuths = _azimuths_for_fov(float(azimuth), float(fov), float(ray_step_deg))
    if azimuths.size == 0:
        azimuths = np.array([0.0], dtype=float)

    sample_azimuths: list[float] = []
    sample_distances: list[float] = []
    sample_states: list[str] = []
    sample_clearances: list[float] = []

    ray_count = 0
    for az in azimuths:
        rad = math.radians(az % 360.0)
        dx = math.sin(rad)
        dy = math.cos(rad)
        distances = np.arange(0.0, float(radius_m) + sample_step_m, sample_step_m, dtype=float)
        if distances.size == 0:
            continue
        xs = np.asarray(observer[0] + dx * distances, dtype=float)
        ys = np.asarray(observer[1] + dy * distances, dtype=float)

        sample_rows = []
        sample_cols = []
        for x, y in zip(xs, ys):
            px, py = _map_to_pixel(transform, x, y)
            sample_rows.append(py)
            sample_cols.append(px)
        sample_rows = np.asarray(sample_rows, dtype=float)
        sample_cols = np.asarray(sample_cols, dtype=float)

        # Skip the first 2 sample points so the observer's own cell cannot self-block its own LOS.
        valid_mask = (
            (sample_rows >= 0.0)
            & (sample_rows < dem.shape[0])
            & (sample_cols >= 0.0)
            & (sample_cols < dem.shape[1])
        )
        valid_idx = np.nonzero(valid_mask)[0]
        if valid_idx.size == 0:
            continue

        valid_idx = valid_idx[2:] if valid_idx.size > 2 else valid_idx[0:0]
        if valid_idx.size == 0:
            continue

        ray_distances = distances[valid_idx]
        ray_heights = np.asarray(
            [
                _sample_bilinear(dem, sample_rows[i], sample_cols[i])
                for i in valid_idx
            ],
            dtype=float,
        )

        if ray_heights.size == 0:
            continue

        effective = ray_heights - (ray_distances * ray_distances) / (2.0 * EARTH_RADIUS_M * REFRACTION_COEFFICIENT)
        skyline_height = observer_eye

        for j, d in enumerate(ray_distances):
            height = float(ray_heights[j])
            adjusted_height = float(effective[j])
            if not np.isfinite(height):
                continue

            if adjusted_height <= observer_eye:
                state = "clear"
                clearance = observer_eye - adjusted_height
            else:
                clearance = adjusted_height - observer_eye
                if adjusted_height > skyline_height:
                    state = "clear"
                    skyline_height = adjusted_height
                else:
                    state = "blocked"
                if clearance <= grazing_margin_m and state == "clear":
                    state = "grazing"

            sample_azimuths.append(float(az))
            sample_distances.append(float(d))
            sample_states.append(state)
            sample_clearances.append(float(clearance))
            ray_count += 1

    samples_dict = {
        "azimuth": np.asarray(sample_azimuths, dtype=float),
        "distance": np.asarray(sample_distances, dtype=float),
        "state": np.asarray(sample_states, dtype=str),
        "clearance": np.asarray(sample_clearances, dtype=float),
    }

    display_distances, display_states, display_clearances = thin_samples_for_display(
        samples_dict["distance"],
        samples_dict["state"],
        samples_dict["clearance"],
    )
    samples = {
        "azimuth": samples_dict["azimuth"][: display_distances.size],
        "distance": display_distances,
        "state": display_states,
        "clearance": display_clearances,
    }

    clear_fraction = float(np.mean(samples_dict["state"] == "clear")) if samples_dict["state"].size else 0.0
    grazing_fraction = float(np.mean(samples_dict["state"] == "grazing")) if samples_dict["state"].size else 0.0
    blocked_fraction = float(np.mean(samples_dict["state"] == "blocked")) if samples_dict["state"].size else 0.0
    mean_clearance = float(np.mean(samples_dict["clearance"])) if samples_dict["clearance"].size else 0.0

    result = SightlineResult(
        observer=tuple(float(v) for v in observer),
        observer_ground_elevation_m=float(observer_ground),
        observer_eye_elevation_m=float(observer_eye),
        radius_m=float(radius_m),
        azimuth=float(azimuth),
        fov=float(fov),
        samples=samples,
        horizon_arcs=_build_horizon_arcs(dem, transform, observer, observer_eye, radius_m, azimuths, sample_step_m),
        stats={
            "clear_fraction": clear_fraction,
            "grazing_fraction": grazing_fraction,
            "blocked_fraction": blocked_fraction,
            "mean_clearance_m": mean_clearance,
        },
    )
    return result
