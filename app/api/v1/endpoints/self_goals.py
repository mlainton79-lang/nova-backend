"""Tony's self-goals endpoints."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.tony_self_goals import (
    list_active_goals, measure_progress, update_goal_progress, ensure_standing_goals
)

router = APIRouter()


@router.get("/self-goals")
async def list_goals(_=Depends(verify_token)):
    ensure_standing_goals()
    update_goal_progress()
    return {"ok": True, "goals": list_active_goals(), "progress": measure_progress()}


@router.post("/self-goals/measure")
async def measure(_=Depends(verify_token)):
    update_goal_progress()
    return {"ok": True, "progress": measure_progress()}
