"""
Tony's case and correspondence management endpoint.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.security import verify_token
from app.core.correspondence import (
    analyse_incoming_letter, draft_response_letter,
    get_case, init_correspondence_tables
)

router = APIRouter()


class LetterAnalysisRequest(BaseModel):
    case_name: str
    letter_text: str
    from_party: str


class ResponseRequest(BaseModel):
    case_name: str
    incoming_analysis: dict
    specific_instruction: str = ""


@router.post("/cases/analyse-letter")
async def analyse_letter(req: LetterAnalysisRequest, _=Depends(verify_token)):
    """Tony reads and analyses an incoming letter."""
    return await analyse_incoming_letter(req.case_name, req.letter_text, req.from_party)


@router.post("/cases/draft-response")
async def draft_response(req: ResponseRequest, _=Depends(verify_token)):
    """Tony drafts a response letter."""
    letter = await draft_response_letter(req.case_name, req.incoming_analysis, req.specific_instruction)
    return {"ok": bool(letter), "letter": letter}


@router.get("/cases/{case_name}")
async def get_case_details(case_name: str, _=Depends(verify_token)):
    """Get details of a specific case."""
    case = await get_case(case_name)
    if not case:
        return {"ok": False, "error": "Case not found"}
    return {"ok": True, "case": case}
