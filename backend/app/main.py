from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.api.ingest import router as ingest_router
from app.api.viewshed import router as viewshed_router
from app.api.ws import router as ws_router


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


app = FastAPI(title="GeoHorizon API", version="0.1.2", lifespan=lifespan)

app.include_router(ingest_router)
app.include_router(viewshed_router)
app.include_router(ws_router)


@app.get("/health")
async def health():
    return {"status": "ok"}