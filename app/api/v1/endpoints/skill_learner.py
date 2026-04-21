"""Skill learner endpoints — Tony proposes new skills from his own experience."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.skill_learner import (
    detect_skill_opportunity, save_proposal, list_proposals,
    approve_proposal, reject_proposal
)

router = APIRouter()


@router.post("/skill-learner/detect")
async def detect(_=Depends(verify_token)):
    """Analyse recent conversations. If a pattern merits a new skill, save proposal."""
    data = await detect_skill_opportunity()
    if not data:
        return {"ok": False, "note": "Detection failed or no data"}
    if not data.get("found"):
        return {"ok": True, "found": False, "reason": data.get("reason")}
    proposal_id = save_proposal(data)
    return {"ok": True, "found": True, "proposal_id": proposal_id, "data": data}


@router.get("/skill-learner/proposals")
async def proposals(status: str = "pending", _=Depends(verify_token)):
    return {"ok": True, "proposals": list_proposals(status)}


@router.post("/skill-learner/proposals/{proposal_id}/approve")
async def approve(proposal_id: int, _=Depends(verify_token)):
    return await approve_proposal(proposal_id)


@router.post("/skill-learner/proposals/{proposal_id}/reject")
async def reject(proposal_id: int, _=Depends(verify_token)):
    return reject_proposal(proposal_id)
