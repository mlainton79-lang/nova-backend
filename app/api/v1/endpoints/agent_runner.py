"""
R2.4 — Agent runner endpoint.

POST /api/v1/agent/run-goal
  body: {goal: str, approval_token?: str}
  returns the full end-to-end trace:
    {ok, plan, execution, error}

Composes app.core.goal_planner.plan_goal + app.core.plan_executor.execute_plan
into a single litmus-test endpoint for the four-layer self-extending-agent
engine. DEV_TOKEN-gated.

To resume a paused plan:
  1. Inspect `execution.paused_step` (likely reason=needs_approval).
  2. POST again with the same `goal` and a non-empty `approval_token`.
  3. The planner re-plans (decomposition is stable enough for v0); the
     executor re-evaluates the governor with the token; ready+approved
     steps execute; the executor halts at the next non-ready step or
     completes.

Future: plan persistence (`tony_plans` table) + a `POST /agent/resume/
{plan_id}` endpoint will let plans span multiple HTTP round-trips
without re-planning. Deferred until R2.5+ proves it's needed.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import verify_token
from app.core.plan_executor import run_goal

router = APIRouter()


class RunGoalRequest(BaseModel):
    goal: str
    approval_token: Optional[str] = None
    # Optional structured/binary inputs that step dispatchers can read by
    # documented keys. Examples: {"images": [{"base64": ..., "mime": ...}]}
    # for vinted_draft_create; {"csv_base64": "..."} for a future CSV
    # capability. Plan-step descriptions can't carry binary data, so
    # payload threads them through the executor to the dispatchers that
    # need them.
    payload: Optional[dict] = None


@router.post("/agent/run-goal")
async def agent_run_goal(body: RunGoalRequest, _=Depends(verify_token)):
    """End-to-end: plan → execute → return trace (or paused state)."""
    if not body.goal or not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required and must be non-empty")
    return await run_goal(
        body.goal,
        approval_token=body.approval_token,
        payload=body.payload,
    )
