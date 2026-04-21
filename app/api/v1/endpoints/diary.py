"""Tony's diary endpoints."""
from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.tony_diary import write_todays_entry, get_recent_diary

router = APIRouter()


@router.post("/diary/write")
async def write_today(_=Depends(verify_token)):
    """Tony writes today's diary entry from today's conversations."""
    return await write_todays_entry()


@router.get("/diary")
async def get_diary(days: int = 7, _=Depends(verify_token)):
    """Read Tony's diary for the last N days."""
    return {"ok": True, "entries": get_recent_diary(days)}
