from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.worker import celery_app
from app.worker.ingestion_tasks import (
    SUPPORTED_EXTS,
    process_elevation_file,
    process_vector_file,
)

IMPORT_DIR = Path("/data/import")

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class StartIngestRequest(BaseModel):
    filename: str


def _classify(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in (".tif", ".vrt"):
        return "raster"
    if suffix == ".pbf":
        return "vector"
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {name}")


@router.get("/scan")
async def scan():
    files = []
    for path in sorted(IMPORT_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        files.append(
            {
                "name": path.name,
                "type": _classify(path.name),
                "size": path.stat().st_size,
            }
        )
    return {"files": files}


@router.post("/start")
async def start(payload: StartIngestRequest):
    filename = payload.filename
    path = IMPORT_DIR / filename

    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")

    file_type = _classify(filename)

    if file_type == "raster":
        task = process_elevation_file.delay(str(path))
    else:
        task = process_vector_file.delay(str(path))

    return {"task_id": task.id, "type": file_type}


@router.get("/status/{task_id}")
async def status(task_id: str):
    result: AsyncResult = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "state": result.state,
        "result": result.result if result.successful() else None,
        "error": str(result.info) if result.failed() else None,
    }