"""Daily review endpoint — end-of-day synthesis."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.daily_review import get_daily_review

router = APIRouter()


@router.get("/review/today")
async def today(_=Depends(verify_token)):
    return await get_daily_review()
