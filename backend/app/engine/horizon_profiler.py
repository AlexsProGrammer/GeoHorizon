"""Horizon ray casting with caching.

Checks whether very distant terrain / mountains (beyond the local viewshed
radius, up to ``max_distance_km``) block the view by casting long rays in the
requested directions. The expensive work — sampling the DEM along each 100 km
ray — is done once per direction relative to a shared origin and cached to
disk as ``.npz`` profiles, so every observer in an area search reuses it.
"""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS, Transformer

__all__ = [
    "HorizonProfile",
    "ray_azimuths",
    "compute_horizon_profiles",
    "observer_distance_along_ray",
    "horizon_fraction",
    "resolve_horizon_scoring",
    "resolve_horizon_pass_threshold",
    "DEFAULT_HORIZON_PASS_THRESHOLD",
]

FALLBACK_CRS_EPSG = 25832
EARTH_RADIUS_M = 6371000.0
DEFAULT_MAX_DISTANCE_KM = 100.0
DEFAULT_SAMPLE_SPACING_M = 100.0
# A 360° sweep uses a fixed number of evenly spaced rays.
PANORAMIC_RAYS = 72
# Directional cones use roughly one ray every N degrees.
DEG_PER_RAY = 5.0


# A viewpoint "passes" when its rays reach, on average, at least this share of
# the requested horizon range. A quarter of a 100 km sweep is a 25 km mean
# sightline: already a strong long-range viewpoint, while still rejecting spots
# walled in by nearby terrain.
DEFAULT_HORIZON_PASS_THRESHOLD = 0.25


@dataclass
class HorizonProfile:
    """Elevation samples along a single ray from a shared origin.

    ``distance`` is in meters from the origin (in the DEM CRS), ``elevation``
    is the DEM value at each step (in meters). Both arrays are the same length.
    ``suffix_max`` is the running maximum elevation from each sample outward,
    derived on construction and used to short-circuit the blocking test.
    """

    azimuth: float
    origin_x: float
    origin_y: float
    distance: np.ndarray
    elevation: np.ndarray
    suffix_max: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # fmax ignores NaN nodata samples.
        self.suffix_max = np.fmax.accumulate(self.elevation[::-1])[::-1]


def _resolve_crs(crs) -> CRS:
    if crs is not None:
        try:
            return CRS.from_user_input(crs)
        except Exception:
            pass
    return CRS.from_epsg(FALLBACK_CRS_EPSG)


def ray_azimuths(azimuth: float, fov: float, num_rays: int | None = None) -> list[float]:
    """Directions (map bearing, degrees) used for the horizon sweep.

    Matches the viewshed: a directional cone uses rays across the FOV (one
    roughly every ``DEG_PER_RAY`` degrees); a 360° panoramic view uses
    ``PANORAMIC_RAYS`` evenly spaced rays.
    """
    if fov >= 360.0:
        n = num_rays or PANORAMIC_RAYS
        return [(360.0 * i) / n for i in range(n)]
    n = num_rays or max(1, int(round(fov / DEG_PER_RAY)))
    start = azimuth - fov / 2
    return [start + (fov * (i + 0.5)) / n for i in range(n)]


def _cache_key(cog_path: str, azimuth: float, max_km: float, spacing_m: float) -> str:
    raw = f"{cog_path}:{azimuth:.4f}:{max_km:.2f}:{spacing_m:.2f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _ray_from_origin(azimuth: float, cx: float, cy: float, distances: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """World (x, y) coordinates along the ray bearing ``azimuth`` from origin."""
    rad = math.radians(azimuth % 360.0)
    dx = math.sin(rad)
    dy = math.cos(rad)
    return cx + dx * distances, cy + dy * distances


def _sampled_elevations(src, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    samples = list(src.sample(list(zip(xs.tolist(), ys.tolist()))))
    values = np.array([s[0] for s in samples], dtype=float)
    nodata = src.nodata
    if nodata is not None:
        values[np.isclose(values, nodata)] = np.nan
    return values


def compute_horizon_profiles(
    cog_path: str,
    center_latlng: tuple[float, float],
    azimuths: list[float],
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    sample_spacing_m: float = DEFAULT_SAMPLE_SPACING_M,
    cache_dir: str | None = None,
) -> dict[float, HorizonProfile]:
    """Compute (or load cached) horizon profiles for each azimuth.

    Rays are cast from ``center_latlng`` (WGS84) outward. Each profile is the
    DEM elevation sampled every ``sample_spacing_m`` up to ``max_distance_km``.
    If ``cache_dir`` is given, profiles are persisted as ``.npz`` and reused.
    """
    max_dist = max_distance_km * 1000.0
    distances = np.arange(0.0, max_dist + sample_spacing_m, sample_spacing_m)
    profiles: dict[float, HorizonProfile] = {}

    cache_dir_path = Path(cache_dir) if cache_dir else None
    if cache_dir_path is not None:
        cache_dir_path.mkdir(parents=True, exist_ok=True)

    # Load any cached profiles first.
    if cache_dir_path is not None:
        for az in azimuths:
            key = _cache_key(cog_path, az, max_distance_km, sample_spacing_m)
            cache_file = cache_dir_path / f"horizon_{key}.npz"
            if cache_file.exists():
                npz = np.load(cache_file, allow_pickle=True)
                profiles[az] = HorizonProfile(
                    azimuth=float(az),
                    origin_x=float(npz["origin_x"]),
                    origin_y=float(npz["origin_y"]),
                    distance=npz["distance"],
                    elevation=npz["elevation"],
                )

    missing = [az for az in azimuths if az not in profiles]
    if not missing:
        return profiles

    with rasterio.open(cog_path) as src:
        src_crs = _resolve_crs(src.crs)
        transformer = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
        cx, cy = transformer.transform(center_latlng[1], center_latlng[0])

        for az in missing:
            xs, ys = _ray_from_origin(az, cx, cy, distances)
            elevation = _sampled_elevations(src, xs, ys)
            profile = HorizonProfile(
                azimuth=az,
                origin_x=cx,
                origin_y=cy,
                distance=distances,
                elevation=elevation,
            )
            profiles[az] = profile

            if cache_dir_path is not None:
                key = _cache_key(cog_path, az, max_distance_km, sample_spacing_m)
                cache_file = cache_dir_path / f"horizon_{key}.npz"
                try:
                    np.savez(
                        cache_file,
                        origin_x=cx,
                        origin_y=cy,
                        distance=distances,
                        elevation=elevation,
                    )
                except Exception:
                    cache_file.unlink(missing_ok=True)

    return profiles


def observer_distance_along_ray(
    azimuth: float,
    origin_x: float,
    origin_y: float,
    obs_x: float,
    obs_y: float,
) -> float:
    """Project an observer position onto the ray axis; the axial distance in meters.

    Useful when the observer is near the shared origin (e.g. inside a compact
    area search): perpendicular offsets are small compared to the ray length.
    """
    rad = math.radians(azimuth % 360.0)
    dx = math.sin(rad)
    dy = math.cos(rad)
    vx = obs_x - origin_x
    vy = obs_y - origin_y
    return vx * dx + vy * dy


def resolve_horizon_scoring(scoring: str | None = None) -> str:
    """Resolve the horizon metric from an override or ``HORIZON_SCORING``.

    ``graded`` (default) reports how far along the ray the view reaches;
    ``binary`` restores the original all-or-nothing blocked/clear result.
    """
    choice = (scoring or os.getenv("HORIZON_SCORING", "graded")).strip().lower()
    return "binary" if choice == "binary" else "graded"


def resolve_horizon_pass_threshold(threshold: float | None = None) -> float:
    """Minimum mean horizon score for a viewpoint to count as unobstructed.

    Overridable per call or via ``HORIZON_PASS_THRESHOLD``; clamped to [0, 1].
    """
    if threshold is None:
        raw = os.getenv("HORIZON_PASS_THRESHOLD")
        if raw is None:
            threshold = DEFAULT_HORIZON_PASS_THRESHOLD
        else:
            try:
                threshold = float(raw)
            except ValueError:
                threshold = DEFAULT_HORIZON_PASS_THRESHOLD
    return min(1.0, max(0.0, float(threshold)))


def horizon_fraction(
    profile: HorizonProfile,
    obs_distance: float,
    eye_altitude: float,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    scoring: str | None = None,
) -> float:
    """How much of the horizon ray the observer can see, in ``[0.0, 1.0]``.

    ``obs_distance`` is the observer's distance along the ray axis and
    ``eye_altitude`` is the observer's eye height (terrain MSL + height above
    ground). Terrain beyond the observer is corrected for Earth curvature; the
    first sample rising above eye level blocks the ray.

    In ``graded`` mode the result is the share of the remaining ray length that
    is reached before that blocker, so a peak at 5 km scores far worse than one
    at 90 km. In ``binary`` mode any blocker yields 0.0. An unobstructed ray, or
    one with no valid samples beyond the observer, scores 1.0.
    """
    max_dist = max_distance_km * 1000.0
    d = profile.distance
    e = profile.elevation

    start = int(np.searchsorted(d, obs_distance, side="right"))
    end = int(np.searchsorted(d, max_dist, side="right"))
    if start >= end:
        return 1.0

    # Curvature only ever lowers terrain, so nothing ahead can block an
    # observer whose eye is already above the highest remaining sample.
    if profile.suffix_max[start] <= eye_altitude:
        return 1.0

    dd = d[start:end] - obs_distance
    effective = e[start:end] - (dd * dd) / (2.0 * EARTH_RADIUS_M)
    # NaN nodata compares False, i.e. it is treated as non-blocking.
    blocked = effective > eye_altitude
    if not np.any(blocked):
        return 1.0
    if resolve_horizon_scoring(scoring) == "binary":
        return 0.0

    span = float(dd[-1])
    if span <= 0.0:
        return 0.0
    return float(dd[int(np.argmax(blocked))] / span)