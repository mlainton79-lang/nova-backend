"""
R2.2 — Goal planner endpoint.

POST /api/v1/planner/plan
  body: {"goal": "...", "approval_token": "..."}  # approval_token optional
  returns the structured plan from app.core.goal_planner.plan_goal()

Read-only — the planner produces plans, it does not execute. Execution
belongs to R2.4. DEV_TOKEN-gated per the standard /api/v1 convention.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import verify_token
from app.core.goal_planner import plan_goal

router = APIRouter()


class PlanGoalRequest(BaseModel):
    goal: str
    approval_token: Optional[str] = None


@router.post("/planner/plan")
async def plan_goal_endpoint(body: PlanGoalRequest, _=Depends(verify_token)):
    """Decompose a goal into ordered steps with registry + governor checks."""
    if not body.goal or not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required and must be non-empty")
    return await plan_goal(body.goal, approval_token=body.approval_token)
