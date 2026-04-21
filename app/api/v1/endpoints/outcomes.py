"""Outcome tracking endpoints — did Tony actually help?"""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.outcome_tracker import get_rolling_satisfaction, recent_bad_outcomes

router = APIRouter()


@router.get("/outcomes/satisfaction")
async def satisfaction(days: int = 7, _=Depends(verify_token)):
    return {"ok": True, **get_rolling_satisfaction(days)}


@router.get("/outcomes/recent-bad")
async def recent_bad(limit: int = 10, _=Depends(verify_token)):
    return {"ok": True, "outcomes": recent_bad_outcomes(limit)}
