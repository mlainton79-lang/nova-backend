"""Tony's goal tracking endpoints."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.goals import (
    get_active_goals, add_goal, update_goal_progress,
    tony_work_on_goals, get_goals_summary
)

router = APIRouter()

@router.get("/goals")
async def list_goals(_=Depends(verify_token)):
    """Get all active goals Tony is working on."""
    return {"goals": get_active_goals(), "summary": get_goals_summary()}

@router.post("/goals")
async def create_goal(
    title: str, description: str,
    category: str = "general", priority: str = "normal",
    next_action: str = None, _=Depends(verify_token)
):
    """Add a new goal for Tony to work on."""
    goal_id = add_goal(title, description, category, priority, next_action)
    return {"id": goal_id, "ok": goal_id > 0}

@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: int, progress: str = None,
    next_action: str = None, blockers: str = None,
    status: str = None, _=Depends(verify_token)
):
    """Update progress on a goal."""
    update_goal_progress(goal_id, progress, next_action, blockers, status)
    return {"ok": True}

@router.post("/goals/work")
async def work_on_goals(_=Depends(verify_token)):
    """Tony autonomously advances his active goals."""
    result = await tony_work_on_goals()
    return {"worked_on": result}
