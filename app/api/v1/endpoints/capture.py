"""Capture endpoints for low-risk notes."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.capture import capture_note
from app.core.security import verify_token


router = APIRouter()


class CaptureNoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    category: Optional[str] = Field("capture", max_length=50)


@router.post("/capture/note")
async def capture_note_endpoint(
    body: CaptureNoteRequest,
    _=Depends(verify_token),
):
    return await capture_note(body.text, category=body.category or "capture")
