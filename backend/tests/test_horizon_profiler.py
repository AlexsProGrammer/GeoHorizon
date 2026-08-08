"""Tests for the horizon ray-casting profiler (Phase 3)."""

from __future__ import annotations

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import from_origin

from app.engine.horizon_profiler import (
    HorizonProfile,
    compute_horizon_profiles,
    horizon_fraction,
    observer_distance_along_ray,
    ray_azimuths,
)

CRS_25832 = CRS.from_epsg(25832)
TRANSFORM = from_origin(500000, 5500200, 10, 10)  # 100x100 @ 10m (~1km incl.)


def _make_cog(path, size=100):
    arr = np.zeros((size, size), dtype=np.float32)
    with rasterio.open(
        str(path), "w", driver="GTiff", height=size, width=size, count=1,
        dtype="float32", crs=CRS_25832, transform=TRANSFORM,
    ) as dst:
        dst.write(arr, 1)


def _center_latlng():
    t = Transformer.from_crs(CRS_25832, "EPSG:4326", always_xy=True)
    lng, lat = t.transform(500500.0, 5499700.0)
    return lat, lng


def test_ray_azimuths_360_is_even_sweep():
    rays = ray_azimuths(90.0, 360.0)
    assert len(rays) == 72
    assert rays[0] == 0.0
    assert rays[-1] == 355.0  # 71 * 5 = 355


def test_ray_azimuths_cone_spans_fov():
    rays = ray_azimuths(270.0, 40.0)
    assert len(rays) == 8  # 40 / 5 = 8 rays
    # Roughly centred on 270° within ±20°.
    assert 250.0 <= 0.5 * (rays[0] + rays[-1]) <= 290.0


def test_horizon_fraction_flat_is_clear_mountain_blocks():
    dist = np.arange(0, 100_100, 100, dtype=float)

    # Flat, low terrain far below the eye level -> clear.
    flat = HorizonProfile(azimuth=270.0, origin_x=0.0, origin_y=0.0, distance=dist, elevation=np.zeros_like(dist))
    assert horizon_fraction(flat, obs_distance=0.0, eye_altitude=10.0, max_distance_km=100.0) == 1.0

    # A mountain (e.g. 1500 m) 30 km out rises above a 10 m eye level -> blocked.
    elev = np.zeros_like(dist)
    peak_idx = np.searchsorted(dist, 30_000)
    elev[peak_idx:] = 1500.0
    mountain = HorizonProfile(azimuth=270.0, origin_x=0.0, origin_y=0.0, distance=dist, elevation=elev)
    assert horizon_fraction(mountain, obs_distance=0.0, eye_altitude=10.0, max_distance_km=100.0) == 0.0

    # A very high observer whose eye is above the mountain -> clear.
    assert horizon_fraction(mountain, obs_distance=0.0, eye_altitude=2000.0, max_distance_km=100.0) == 1.0


def test_observer_distance_along_ray():
    # Observer directly north (0°) of the origin -> distance equals northing delta.
    assert observer_distance_along_ray(0.0, 0.0, 0.0, 0.0, 500.0) == 500.0
    # East (90°) -> distance equals easting delta.
    assert observer_distance_along_ray(90.0, 0.0, 0.0, 500.0, 0.0) == 500.0
    # West (270°) -> negative easting delta along the ray.
    assert observer_distance_along_ray(270.0, 0.0, 0.0, -500.0, 0.0) == 500.0


def test_compute_horizon_profiles_and_cache(tmp_path, monkeypatch):
    cog = tmp_path / "cog.tif"
    _make_cog(cog)
    center = _center_latlng()
    cache_dir = tmp_path / "horizon_cache"

    profiles = compute_horizon_profiles(
        str(cog), center, [0.0, 90.0, 180.0], max_distance_km=3.0, cache_dir=str(cache_dir)
    )
    assert set(profiles.keys()) == {0.0, 90.0, 180.0}
    for p in profiles.values():
        assert p.distance.shape == p.elevation.shape
        assert p.distance.size > 10

    files = list(cache_dir.glob("horizon_*.npz"))
    assert len(files) == 3

    # A second call should load from cache (no re-sampling) and match azimuths.
    again = compute_horizon_profiles(
        str(cog), center, [0.0, 90.0, 180.0], max_distance_km=3.0, cache_dir=str(cache_dir)
    )
    assert set(again.keys()) == set(profiles.keys())