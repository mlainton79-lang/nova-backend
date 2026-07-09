"""
Think endpoints - compatibility routes for Nova's briefing/cognition surface.
"""
from fastapi import APIRouter, Depends

from app.core.security import verify_token


router = APIRouter()


@router.get("/think/morning")
async def morning_brief(_=Depends(verify_token)):
    """Return the same intelligent morning brief used by proactive briefings."""
    from app.core.intelligent_briefing import get_intelligent_briefing

    return await get_intelligent_briefing()
