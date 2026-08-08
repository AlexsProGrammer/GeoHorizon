"""DSM (Digital Surface Model) builder.

Extracts a localized DEM window from a Cloud Optimized GeoTIFF (COG) and
overlays PostGIS obstacle geometries (buildings + forests) onto the terrain.
"""

from __future__ import annotations

__all__ = [
    "get_bounding_box",
    "crop_dem_window",
    "fetch_obstacles",
    "build_dsm",
]


def get_bounding_box(lat: float, lng: float, radius_km: float, src_crs):
    """Implement Phase 2.1: CRS-aware observer bounding box."""
    raise NotImplementedError


def crop_dem_window(cog_path: str, bbox):
    """Implement Phase 2.2: windowed COG read."""
    raise NotImplementedError


def fetch_obstacles(db_session, bbox_polygon):
    """Implement Phase 2.3: query PostGIS buildings & forests."""
    raise NotImplementedError


def build_dsm(dem_array, transform, buildings_gdf, forests_gdf,
              tree_height_override=None, building_height_override=None):
    """Implement Phase 2.4: rasterize obstacles onto the DEM."""
    raise NotImplementedError
