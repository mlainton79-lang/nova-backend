"""Fabrication detection endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import verify_token
from app.core.fabrication_detector import list_recent_suspicions, mark_verdict

router = APIRouter()


@router.get("/fabrications")
async def recent(_=Depends(verify_token)):
    """Recent suspected fabrications, pending review."""
    return {"ok": True, "suspicions": list_recent_suspicions()}


class VerdictRequest(BaseModel):
    fabrication_id: int
    verdict: str  # 'confirmed_fabrication' | 'actually_true' | 'inconclusive'


@router.post("/fabrications/verdict")
async def verdict(req: VerdictRequest, _=Depends(verify_token)):
    ok = mark_verdict(req.fabrication_id, req.verdict)
    return {"ok": ok}
