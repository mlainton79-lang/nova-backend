"""
Text summarisation endpoint.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import verify_token
from app.core.summarise import summarise_text


router = APIRouter()


class SummariseRequest(BaseModel):
    text: str
    instruction: Optional[str] = None
    max_sentences: int = 5


@router.post("/summarise/")
@router.post("/summarise")
async def summarise(req: SummariseRequest, _=Depends(verify_token)):
    result = await summarise_text(
        req.text,
        instruction=req.instruction,
        max_sentences=req.max_sentences,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "summarise failed"))
    return result
