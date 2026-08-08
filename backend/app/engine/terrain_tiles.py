"""Terrain-RGB tile rendering for MapLibre 3D terrain.

Generates Mapbox terrain-RGB encoded PNG tiles from a DEM COG on demand, so the
map can render 3D hills and valleys. Tiles are cached to disk keyed by the COG
path + mtime + tile coordinate to avoid re-warping on every request.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pyproj import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject

__all__ = ["render_terrain_tile"]

FALLBACK_CRS_EPSG = 25832
WORLD_MERCADOR = 20037508.342789244
MAX_TILE_ZOOM = 15
TILE_SIZE = 256
NODATA_ELEV = -9999.0
CACHE_MAXAGE_SECONDS = 7 * 24 * 3600  # drop stale cache entries after a week


def _resolve_crs(crs) -> CRS:
    if crs is not None:
        try:
            return CRS.from_user_input(crs)
        except Exception:
            pass
    return CRS.from_epsg(FALLBACK_CRS_EPSG)


def _tile_mercator_bounds(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """Web-Mercator (EPSG:3857) bounds of a slippy-map tile (z, x, y)."""
    size = WORLD_MERCADOR * 2.0 / (1 << z)
    minx = -WORLD_MERCADOR + x * size
    maxx = -WORLD_MERCADOR + (x + 1) * size
    # y=0 is the top (north) edge, i.e. +WORLD_MERCADOR.
    maxy = WORLD_MERCADOR - y * size
    miny = WORLD_MERCADOR - (y + 1) * size
    return minx, miny, maxx, maxy


def _encode_mapbox(elev: np.ndarray) -> np.ndarray:
    """Encode elevations (m) as a standard Mapbox terrain-RGB (R,G,B) 8-bit array.

    The 24-bit integer stored in RGB is ``round((elevation_m + 10000) * 10)``
    and MapLibre decodes it back with::

        elevation = (R * 256² + G * 256 + B) * 0.1 - 10000

    (See the Mapbox terrain-RGB spec; this is what MapLibre's ``raster-dem``
    source with ``encoding: 'mapbox'`` expects.) Encoding the plain ``elev+10000``
    without the ``*10`` scale made MapLibre decode every value ~10x too small and
    shifted by +10000, producing elevations near zero / hugely negative.
    """
    shape = elev.shape
    out = np.zeros((3, *shape), dtype=np.uint8)
    valid = np.isfinite(elev) & (elev > -9000.0)
    ee = np.clip(np.rint((elev[valid] + 10000.0) * 10.0), 0.0, 16777215.0).astype(np.int64)
    out[0][valid] = (ee >> 16) & 0xFF
    out[1][valid] = (ee >> 8) & 0xFF
    out[2][valid] = ee & 0xFF
    # Invalid / no-data stays (0,0,0) which decodes to -10000 m (far below sea).
    return out


def _cache_path(cache_dir: Path, cog_path: str, src_mtime: float, x: int, y: int, z: int) -> Path:
    key = hashlib.sha256(
        f"{cog_path}:{src_mtime:.3f}:{z}/{x}/{y}".encode()
    ).hexdigest()[:16]
    return cache_dir / f"{key}.png"


def render_terrain_tile(cog_path: str, x: int, y: int, z: int, cache_dir: str | None = None) -> bytes | None:
    """Render one terrain-RGB PNG tile (bytes) covering the given CRS tile.

    Returns ``None`` if the COG does not intersect the tile or cannot be read.
    """
    if z > MAX_TILE_ZOOM:
        z = MAX_TILE_ZOOM

    cache_path = None
    if cache_dir:
        cache_dir_path = Path(cache_dir)
        cache_dir_path.mkdir(parents=True, exist_ok=True)
        src_mtime = Path(cog_path).stat().st_mtime
        cache_path = _cache_path(cache_dir_path, cog_path, src_mtime, x, y, z)
        # Purge stale entries occasionally.
        _prune_cache(cache_dir_path)
        if cache_path.exists():
            return cache_path.read_bytes()

    minx, miny, maxx, maxy = _tile_mercator_bounds(x, y, z)
    target_transform = from_bounds(minx, miny, maxx, maxy, TILE_SIZE, TILE_SIZE)

    try:
        with rasterio.open(cog_path) as src:
            src_crs = _resolve_crs(src.crs)
            dst = np.empty((TILE_SIZE, TILE_SIZE), dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=dst,
                src_transform=src.transform,
                src_crs=src_crs,
                dst_transform=target_transform,
                dst_crs="EPSG:3857",
                resampling=Resampling.bilinear,
                dst_nodata=NODATA_ELEV,
                init_dest_nodata=NODATA_ELEV,
            )
    except Exception:
        return None

    rgb = _encode_mapbox(dst)
    png_bytes = _to_png(rgb)

    if cache_path is not None:
        try:
            cache_path.write_bytes(png_bytes)
        except Exception:
            pass
    return png_bytes


def _to_png(rgb: np.ndarray) -> bytes:
    """Serialize a (3, h, w) uint8 array to PNG bytes (RGB, no alpha)."""
    img = Image.fromarray(np.moveaxis(rgb, 0, -1))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _prune_cache(cache_dir: Path) -> None:
    try:
        now = datetime.now(timezone.utc).timestamp()
        for f in cache_dir.iterdir():
            if f.is_file() and f.name.endswith(".png"):
                try:
                    if now - f.stat().st_mtime > CACHE_MAXAGE_SECONDS:
                        f.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass