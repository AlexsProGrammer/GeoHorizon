"""WebSocket router for real-time task progress streaming."""

from __future__ import annotations

import json
import os

import redis.asyncio as redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://redis:6379/0")


@router.websocket("/ws/progress/{task_id}")
async def progress_ws(websocket: WebSocket, task_id: str):
    """Stream progress updates for a task over a WebSocket connection.

    Subscribes to the Redis Pub/Sub channel ``task_progress:{task_id}`` and
    forwards each published message verbatim as JSON text to the client.
    """
    await websocket.accept()
    await websocket.send_text(
        json.dumps(
            {"task_id": task_id, "status": "CONNECTED", "progress": 0, "step": "Listening for updates"}
        )
    )

    r = None
    pubsub = None
    try:
        r = redis.from_url(_redis_url(), decode_responses=True)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"task_progress:{task_id}")

        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if msg is not None:
                data = msg.get("data")
                if data is not None:
                    await websocket.send_text(data)
    except WebSocketDisconnect:
        pass
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(f"task_progress:{task_id}")
                await pubsub.close()
            except Exception:
                pass
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
