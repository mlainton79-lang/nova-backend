"""Self-improvement proposal endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.self_improvement import (
    analyse_eval_failures, list_pending_proposals, mark_proposal
)

router = APIRouter()


@router.get("/self_improvement/proposals")
async def pending(_=Depends(verify_token)):
    """List pending improvement proposals."""
    return {"ok": True, "proposals": list_pending_proposals()}


class AnalyseRequest(BaseModel):
    eval_run_id: int


@router.post("/self_improvement/analyse")
async def analyse(req: AnalyseRequest, _=Depends(verify_token)):
    """Run the analyser on a specific eval run."""
    props = await analyse_eval_failures(req.eval_run_id)
    return {"ok": True, "proposals_created": len(props), "proposals": props}


class MarkRequest(BaseModel):
    proposal_id: int
    status: str  # 'applied' or 'dismissed'


@router.post("/self_improvement/mark")
async def mark(req: MarkRequest, _=Depends(verify_token)):
    ok = mark_proposal(req.proposal_id, req.status)
    return {"ok": ok}
