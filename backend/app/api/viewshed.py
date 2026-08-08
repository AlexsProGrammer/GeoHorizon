from celery.result import AsyncResult
from fastapi import APIRouter
from pydantic import BaseModel

from app.worker import celery_app
from app.worker.viewshed_tasks import run_viewshed_task

router = APIRouter(prefix="/api/viewshed", tags=["viewshed"])


class ViewshedRequest(BaseModel):
    cog_path: str
    lat: float
    lng: float
    radius_km: float
    azimuth: float
    fov: float
    observer_height: float = 1.8
    tree_height: float = 30.0
    building_height: float = 15.0


@router.post("/start")
async def start(payload: ViewshedRequest):
    task = run_viewshed_task.delay(payload.model_dump())
    return {"task_id": task.id}


@router.get("/status/{task_id}")
async def status(task_id: str):
    result: AsyncResult = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "state": result.state,
        "result": result.result if result.successful() else None,
        "error": str(result.info) if result.failed() else None,
    }
