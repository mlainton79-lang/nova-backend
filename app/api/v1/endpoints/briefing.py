"""Daily briefing endpoints."""
from fastapi import APIRouter, Depends

from app.core.security import verify_token
from app.core.today_brief import get_today_brief


router = APIRouter()


@router.get("/briefing/today")
async def briefing_today(_=Depends(verify_token)):
    return await get_today_brief()
