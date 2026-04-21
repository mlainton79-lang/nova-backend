"""Agentic executor endpoint — multi-step goal execution."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.agentic_executor import run_agentic_goal

router = APIRouter()


class GoalRequest(BaseModel):
    goal: str
    max_steps: int = 8


@router.post("/agentic/run")
async def run_goal(req: GoalRequest, _=Depends(verify_token)):
    """Execute a multi-step goal via plan-act-observe loop."""
    return await run_agentic_goal(req.goal, max_steps=min(req.max_steps, 12))
