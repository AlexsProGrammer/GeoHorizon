from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.ingest import router as ingest_router
from app.api.viewshed import router as viewshed_router
from app.api.ws import router as ws_router

TILES_DIR = Path("/data/pmtiles")
TILES_DIR.mkdir(parents=True, exist_ok=True)


def run_migrations() -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option(
        "script_location", "/app/alembic"
    )
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="GeoHorizon API", version="0.1.12", lifespan=lifespan)

app.mount("/tiles", StaticFiles(directory=TILES_DIR), name="tiles")

app.include_router(ingest_router)
app.include_router(viewshed_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}