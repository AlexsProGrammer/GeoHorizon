"""Area-search performance benchmark.

Times a multi-point area search end-to-end through both viewshed engines and
reports the speedup of the in-memory NumPy engine over the legacy
WhiteboxTools engine (the "before / after" comparison from the performance
plan). A small synthetic COG is generated on the fly so no external data,
database or Celery is required.

Usage (run from the backend directory)::

    python -m app.benchmark                       # 1 km² area @ 100 m step
    python -m app.benchmark --grid-step 50        # finer grid (more points)
    python -m app.benchmark --area-km 0.5
    python -m app.benchmark --engine numpy        # time only one engine
    python -m app.benchmark --assert-threshold 4  # exit 1 if speedup < 4x

The reference configuration from the plan is a 1 km² search area at a 50 m
grid step (~400 points); pass ``--grid-step 50`` for exactly that.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import from_origin

import app.engine.area_search as area_search
from app.engine.area_search import run_area_search

CRS_25832 = CRS.from_epsg(25832)
PIXEL_SIZE = 10.0


def _make_cog(path: Path, size: int = 200) -> None:
    """Write a small synthetic DEM (ramp + hills) to ``path``."""
    rows = np.arange(size, dtype=np.float64)
    cols = np.arange(size, dtype=np.float64)
    grid = rows[:, None] + cols[None, :]
    arr = (
        600.0
        + grid * 0.8
        + np.sin(cols[None, :] / 6.0) * 12.0
        + np.sin(rows[:, None] / 4.0) * 18.0
    ).astype(np.float32)
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="float32",
        crs=CRS_25832,
        transform=from_origin(500000, 5500200, PIXEL_SIZE, PIXEL_SIZE),
    ) as dst:
        dst.write(arr, 1)


def _search_polygon_wgs84(area_km: float):
    """A WGS84 square of ``area_km`` x ``area_km`` centred mid-COG."""
    side = area_km * 1000.0
    centre_x, centre_y = 501000.0, 5499300.0
    minx, miny = centre_x - side / 2, centre_y - side / 2
    maxx, maxy = centre_x + side / 2, centre_y + side / 2

    t = Transformer.from_crs(CRS_25832, "EPSG:4326", always_xy=True)
    (minlng, minlat) = t.transform(minx, miny)
    (maxlng, maxlat) = t.transform(maxx, maxy)
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [minlng, minlat],
                [maxlng, minlat],
                [maxlng, maxlat],
                [minlng, maxlat],
                [minlng, minlat],
            ]
        ],
    }


def _patch_obstacles() -> None:
    """Point ``area_search.fetch_obstacles`` at empty frames for the run."""
    empty = gpd.GeoDataFrame(geometry=[])
    area_search.fetch_obstacles = lambda *a, **k: (empty, empty)


def _time_engine(cog_path: str, engine: str, area_km: float, grid_step: float) -> tuple[float, dict]:
    t0 = time.perf_counter()
    fc = run_area_search(
        db_session=None,
        cog_path=cog_path,
        search_area_geojson=_search_polygon_wgs84(area_km),
        radius_km=0.1,
        azimuth=270.0,
        fov=360.0,
        grid_step_m=grid_step,
        engine=engine,
    )
    elapsed = time.perf_counter() - t0
    return elapsed, fc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-step", type=float, default=100.0, help="grid spacing in metres")
    parser.add_argument("--area-km", type=float, default=1.0, help="search area side in km")
    parser.add_argument(
        "--engine",
        choices=("both", "numpy", "whitebox"),
        default="both",
        help="which engine(s) to time (default: both)",
    )
    parser.add_argument(
        "--assert-threshold",
        type=float,
        default=None,
        help="exit non-zero unless the numpy/whitebox speedup is >= this many x",
    )
    parser.add_argument("--json", action="store_true", help="emit results as JSON")
    args = parser.parse_args(argv)

    original_fetch = area_search.fetch_obstacles
    _patch_obstacles()
    tmpdir = tempfile.mkdtemp(prefix="benchmark_")
    try:
        cog = Path(tmpdir) / "benchmark_cog.tif"
        _make_cog(cog)

        results: dict[str, float] = {}
        count = 0

        if args.engine in ("whitebox", "both"):
            t_whitebox, fc = _time_engine(str(cog), "whitebox", args.area_km, args.grid_step)
            results["whitebox"] = round(t_whitebox, 3)
            count = int(fc.get("meta", {}).get("count", 0))

        if args.engine in ("numpy", "both"):
            t_numpy, fc = _time_engine(str(cog), "numpy", args.area_km, args.grid_step)
            results["numpy"] = round(t_numpy, 3)
            count = int(fc.get("meta", {}).get("count", 0))

        speedup = None
        if "whitebox" in results and "numpy" in results and results["numpy"] > 0:
            speedup = round(results["whitebox"] / results["numpy"], 2)
            results["speedup_x"] = speedup

        summary = {
            "area_km": args.area_km,
            "grid_step_m": args.grid_step,
            "points": count,
            "elapsed_s": results,
        }

        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Search area : {args.area_km:.2f} km x {args.area_km:.2f} km")
            print(f"Grid step   : {args.grid_step:g} m  ({count} points)")
            if "whitebox" in results:
                print(f"Whitebox    : {results['whitebox']:.3f} s")
            if "numpy" in results:
                print(f"NumPy       : {results['numpy']:.3f} s")
            if speedup is not None:
                print(f"Speedup     : {speedup:.2f}x")

        if args.assert_threshold is not None:
            if speedup is None:
                print("ERROR: cannot assert a speedup when only one engine was timed")
                return 1
            if speedup < args.assert_threshold:
                print(
                    f"FAIL: speedup {speedup:.2f}x < required {args.assert_threshold:.1f}x"
                )
                return 1
            print(f"PASS: speedup {speedup:.2f}x >= {args.assert_threshold:.1f}x")
        return 0
    finally:
        area_search.fetch_obstacles = original_fetch
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())