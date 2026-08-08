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
from dataclasses import dataclass
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
]

FALLBACK_CRS_EPSG = 25832
EARTH_RADIUS_M = 6371000.0
DEFAULT_MAX_DISTANCE_KM = 100.0
DEFAULT_SAMPLE_SPACING_M = 100.0
# A 360° sweep uses a fixed number of evenly spaced rays.
PANORAMIC_RAYS = 72
# Directional cones use roughly one ray every N degrees.
DEG_PER_RAY = 5.0


@dataclass
class HorizonProfile:
    """Elevation samples along a single ray from a shared origin.

    ``distance`` is in meters from the origin (in the DEM CRS), ``elevation``
    is the DEM value at each step (in meters). Both arrays are the same length.
    """

    azimuth: float
    origin_x: float
    origin_y: float
    distance: np.ndarray
    elevation: np.ndarray


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


def horizon_fraction(
    profile: HorizonProfile,
    obs_distance: float,
    eye_altitude: float,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
) -> float:
    """Whether the horizon ray is unobstructed for an observer.

    ``obs_distance`` is the observer's distance along the ray axis and
    ``eye_altitude`` is the observer's eye height (terrain MSL + height above
    ground). The ray is blocked if any terrain beyond the observer, corrected
    for Earth curvature, rises above eye level. Returns 1.0 if clear, 0.0 if
    blocked. If no valid samples exist beyond the observer, assumes clear.
    """
    max_dist = max_distance_km * 1000.0
    d = profile.distance
    e = profile.elevation
    beyond = (d > obs_distance) & (d <= max_dist) & np.isfinite(e)
    if not np.any(beyond):
        return 1.0
    dd = d[beyond] - obs_distance
    curvature = (dd * dd) / (2.0 * EARTH_RADIUS_M)
    effective = e[beyond] - curvature
    if np.any(effective > eye_altitude):
        return 0.0
    return 1.0