from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI


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


app = FastAPI(title="GeoHorizon API", version="0.1.1", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}