"""DSM (Digital Surface Model) builder.

Extracts a localized DEM window from a Cloud Optimized GeoTIFF (COG) and
overlays PostGIS obstacle geometries (buildings + forests) onto the terrain.
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio import features
from rasterio.windows import Window, from_bounds, transform

__all__ = [
    "get_bounding_box",
    "crop_dem_window",
    "fetch_obstacles",
    "build_dsm",
]

FOREST_DEFAULT_HEIGHT = 30.0
BUILDING_DEFAULT_HEIGHT = 15.0

# Fallback projected CRS when a DEM sources declares no coordinate system.
# The bundled Bavarian DEM is ETRS89 / UTM zone 32N.
FALLBACK_CRS_EPSG = 25832


def get_bounding_box(lat: float, lng: float, radius_km: float, src_crs) -> tuple:
    """Return a square (minx, miny, maxx, maxy) bounding box of 2*radius side.

    The observer coordinate is given in WGS84 (EPSG:4326) and is transformed
    into the DEM's native projected CRS before deriving the box. If ``src_crs``
    is missing/empty the configured fallback (EPSG:25832) is used.
    """
    if src_crs is None:
        src_crs = CRS.from_epsg(FALLBACK_CRS_EPSG)
    transformer = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
    x, y = transformer.transform(lng, lat)
    half = radius_km * 1000.0
    return (x - half, y - half, x + half, y + half)


def crop_dem_window(cog_path: str, bbox: tuple) -> tuple[np.ndarray, Any, Any]:
    """Read only the DEM window covering ``bbox`` (in src CRS units).

    Returns ``(elevation_array, affine_transform, crs)``. Only the requested
    window is loaded into RAM, never the full COG.
    """
    with rasterio.open(cog_path) as src:
        win: Window = from_bounds(*bbox, transform=src.transform)
        array = src.read(1, window=win)
        win_transform = transform(win, src.transform)
        return array, win_transform, src.crs


def fetch_obstacles(db_session, bbox_polygon) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Query the ``buildings`` and ``forests`` PostGIS tables intersecting the
    bbox polygon (EPSG:4326). Returns ``(buildings_gdf, forests_gdf)``.
    """
    wkt = getattr(bbox_polygon, "wkt", str(bbox_polygon))
    bind = db_session.get_bind()

    # NOTE on the two SQL details below:
    #  - geopandas.read_postgis parses the geometry column with
    #    ``shapely.wkb.loads(..., hex=True)``, i.e. it expects EWKB encoded as
    #    hex text, NOT human-readable WKT. Hence ST_AsHexEWKB(geom).
    #  - read_postgis passes ``params`` straight to psycopg2 (via
    #    ``exec_driver_sql``), which uses pyformat placeholders (``%(name)s``),
    #    not SQLAlchemy's ``:name`` syntax.
    buildings_sql = (
        "SELECT id, name, estimated_height, ST_AsHexEWKB(geom) AS geom "
        "FROM buildings WHERE ST_Intersects(geom, ST_GeomFromText(%(wkt)s, 4326))"
    )
    forests_sql = (
        "SELECT id, name, estimated_height, ST_AsHexEWKB(geom) AS geom "
        "FROM forests WHERE ST_Intersects(geom, ST_GeomFromText(%(wkt)s, 4326))"
    )

    buildings_gdf = gpd.read_postgis(
        buildings_sql, bind, geom_col="geom", crs="EPSG:4326", params={"wkt": wkt}
    )
    forests_gdf = gpd.read_postgis(
        forests_sql, bind, geom_col="geom", crs="EPSG:4326", params={"wkt": wkt}
    )
    return buildings_gdf, forests_gdf


def _rasterize_obstacles(
    gdf: gpd.GeoDataFrame | None,
    transform,
    out_shape: tuple,
    crs,
    default_height: float,
    height_override: float | None,
) -> np.ndarray:
    """Rasterize a GeoDataFrame of polygons into a height mask matching ``transform``."""
    mask = np.zeros(out_shape, dtype=np.float64)
    if gdf is None or gdf.empty:
        return mask

    if crs is not None and gdf.crs is not None and gdf.crs.to_epsg() != crs.to_epsg():
        gdf = gdf.to_crs(crs)

    if height_override is not None:
        heights = np.full(len(gdf), float(height_override))
    elif "estimated_height" in gdf.columns:
        heights = gdf["estimated_height"].fillna(default_height).astype(float).to_numpy()
    else:
        heights = np.full(len(gdf), float(default_height))

    shapes = [
        (geom, float(h)) for geom, h in zip(gdf.geometry, heights) if not geom.is_empty
    ]
    if shapes:
        mask = features.rasterize(
            shapes,
            out_shape=out_shape,
            transform=transform,
            fill=0,
            all_touched=True,
            dtype=np.float64,
        )
    return mask


def build_dsm(
    dem_array: np.ndarray,
    transform,
    buildings_gdf: gpd.GeoDataFrame | None,
    forests_gdf: gpd.GeoDataFrame | None,
    crs=None,
    tree_height_override: float | None = None,
    building_height_override: float | None = None,
) -> np.ndarray:
    """Combine the DEM with rasterized obstacle heights element-wise.

    ``dsm = dem + tree_mask + building_mask``. Obstacles are reprojected into
    the DEM's CRS (``crs``) before rasterization.
    """
    out_shape = dem_array.shape

    tree_mask = _rasterize_obstacles(
        forests_gdf, transform, out_shape, crs, FOREST_DEFAULT_HEIGHT, tree_height_override
    )
    building_mask = _rasterize_obstacles(
        buildings_gdf, transform, out_shape, crs, BUILDING_DEFAULT_HEIGHT, building_height_override
    )

    return dem_array.astype(np.float64) + tree_mask + building_mask
