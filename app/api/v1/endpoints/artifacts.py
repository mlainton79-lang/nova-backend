"""Artifact extraction endpoint — identify canvas-worthy content in a reply."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.security import verify_token
from app.core.artifact_extractor import extract_artifacts

router = APIRouter()


class ExtractRequest(BaseModel):
    reply: str
    user_message: Optional[str] = ""


@router.post("/artifacts/extract")
async def extract(req: ExtractRequest, _=Depends(verify_token)):
    artifacts = extract_artifacts(req.reply, req.user_message or "")
    return {"ok": True, "count": len(artifacts), "artifacts": artifacts}
