from pathlib import Path

import geopandas as gpd
import rasterio
from pyrosm import OSM
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles

from app.core.db import SessionLocal
from app.models.gis import Building, Forest
from app.worker import celery_app

PROCESSED_DIR = "/data/processed"
RASTER_EXTS = (".tif", ".vrt")
VECTOR_EXTS = (".pbf",)
SUPPORTED_EXTS = RASTER_EXTS + VECTOR_EXTS


def _prepare_frame(df, default_height: int):
    if df is None or df.empty:
        return None
    if df.crs is None:
        df = df.set_crs(crs="EPSG:4326")
    elif df.crs.to_epsg() != 4326:
        df = df.to_crs(epsg=4326)

    df = df[df.geometry.notnull() & df.geometry.is_valid & ~df.geometry.is_empty]
    if df.empty:
        return None

    df = df.copy()
    if "estimated_height" not in df.columns:
        df["estimated_height"] = default_height
    else:
        df["estimated_height"] = df["estimated_height"].fillna(default_height).astype(int)

    df = df.rename(columns={"geometry": "geom"}).set_geometry("geom")
    return df[["estimated_height", "geom"]]


@celery_app.task(bind=True, name="ingestion.process_elevation_file")
def process_elevation_file(self, file_path: str):
    path = Path(file_path)
    if path.suffix.lower() not in RASTER_EXTS:
        raise ValueError(f"Unsupported elevation file: {file_path}")

    out_path = Path(PROCESSED_DIR) / f"{path.stem}_cog.tif"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    profile = cog_profiles["deflate"]
    with rasterio.open(path) as src:
        cog_translate(
            src,
            str(out_path),
            profile,
            overview_level=6,
            overview_resampling="average",
            dtype=src.dtypes[0],
            nodata=src.nodata,
            config={"GDAL_NUM_THREADS": "ALL_CPUS"},
        )

    return {"status": "success", "output": str(out_path)}


@celery_app.task(bind=True, name="ingestion.process_vector_file")
def process_vector_file(self, file_path: str):
    path = Path(file_path)
    if path.suffix.lower() not in VECTOR_EXTS:
        raise ValueError(f"Unsupported vector file: {file_path}")

    osm = OSM(str(path))
    buildings_df = osm.get_buildings()

    try:
        forests_df = osm.get_data_by_custom_criteria(
            {"natural": ["wood"], "landuse": ["forest"]}
        )
    except Exception:
        forests_df = None

    buildings = _prepare_frame(buildings_df, default_height=10)
    forests = _prepare_frame(forests_df, default_height=30)

    engine = SessionLocal().get_bind()
    buildings_count = 0
    forests_count = 0

    if buildings is not None and not buildings.empty:
        buildings.to_postgis(
            Building.__tablename__,
            engine,
            if_exists="append",
            index=False,
        )
        buildings_count = len(buildings)

    if forests is not None and not forests.empty:
        forests.to_postgis(
            Forest.__tablename__,
            engine,
            if_exists="append",
            index=False,
        )
        forests_count = len(forests)

    return {"status": "success", "buildings": buildings_count, "forests": forests_count}