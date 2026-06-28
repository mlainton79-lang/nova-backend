"""Protected Tony Codex handoff endpoints."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.codex_task_handoff import (
    create_pending_codex_task,
    get_next_pending_codex_task,
    ingest_codex_task_report,
)
from app.core.security import verify_token


router = APIRouter()


class CodexTaskPlanRequest(BaseModel):
    user_goal: str
    tool_or_area: str = "nova-backend"
    allowed_files_or_areas: Optional[List[str]] = None
    blocked_files_or_areas: Optional[List[str]] = None
    can_edit_code: bool = True
    can_run_tests: bool = True
    can_commit: bool = False
    can_push_branch: bool = False
    can_deploy: bool = False
    requires_matthew_approval_before_deploy: bool = True


class CodexTaskReportRequest(BaseModel):
    status: str = "ready_to_report"
    changed_files_summary: List[str] = Field(default_factory=list)
    tests_summary: List[str] = Field(default_factory=list)
    deployment_summary: str = "not_attempted"
    final_report: str = "Local Codex handoff report received."
    codex_execution_invoked: bool = False
    external_apis_called: bool = False
    github_mutation_performed: bool = False
    railway_mutation_performed: bool = False
    secrets_exposed: bool = False


@router.post("/codex-tasks/plan")
async def create_codex_task_plan_endpoint(
    request: CodexTaskPlanRequest,
    _=Depends(verify_token),
):
    """Create a safe pending Codex task for a local runner."""
    try:
        task = create_pending_codex_task(
            user_goal=request.user_goal,
            tool_or_area=request.tool_or_area,
            allowed_files_or_areas=tuple(request.allowed_files_or_areas or ()),
            blocked_files_or_areas=tuple(request.blocked_files_or_areas or ()),
            can_edit_code=request.can_edit_code,
            can_run_tests=request.can_run_tests,
            can_commit=request.can_commit,
            can_push_branch=request.can_push_branch,
            can_deploy=request.can_deploy,
            requires_matthew_approval_before_deploy=(
                request.requires_matthew_approval_before_deploy
            ),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "created": True, "task": task}


@router.get("/codex-tasks/next")
async def get_next_codex_task_endpoint(_=Depends(verify_token)):
    """Return the next pending safe Codex task for Matthew's local runner."""
    task = get_next_pending_codex_task()
    if not task:
        return {"ok": True, "found": False, "task": None}
    return {"ok": True, "found": True, "task": task}


@router.post("/codex-tasks/{task_id}/report")
async def report_codex_task_endpoint(
    task_id: str,
    request: CodexTaskReportRequest,
    _=Depends(verify_token),
):
    """Accept sanitized local-runner result metadata."""
    try:
        report = ingest_codex_task_report(task_id, request.dict())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"ok": True, "accepted": True, "report": report}
