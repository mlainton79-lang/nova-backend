"""
Endpoints for querying Tony's background tasks.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional, Dict
from app.core.security import verify_token
from app.core.task_queue import (
    queue_task, get_task, list_active_tasks
)

router = APIRouter()


class QueueTaskRequest(BaseModel):
    task_type: str
    payload: Dict = {}
    delay_seconds: int = 0


@router.post("/tasks/queue")
async def queue_new_task(req: QueueTaskRequest, _=Depends(verify_token)):
    task_id = queue_task(req.task_type, req.payload, req.delay_seconds)
    return {"ok": task_id > 0, "task_id": task_id}


@router.get("/tasks/{task_id}")
async def task_status(task_id: int, _=Depends(verify_token)):
    task = get_task(task_id)
    if not task:
        return {"ok": False, "error": "Task not found"}
    return {"ok": True, "task": task}


@router.get("/tasks")
async def list_tasks(_=Depends(verify_token)):
    return {"ok": True, "tasks": list_active_tasks()}
