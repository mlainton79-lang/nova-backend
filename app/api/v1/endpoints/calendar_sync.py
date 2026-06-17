"""
Samsung calendar sync endpoint.

Receives device-calendar event batches from the Android app and persists
them to samsung_calendar_events. proactive_scheduler reads from the same
table.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import verify_token
from app.core.samsung_calendar import upsert_events

router = APIRouter()


class CalendarEvent(BaseModel):
    event_id: str
    calendar_id: str
    title: str
    start_ms: int
    end_ms: int
    all_day: bool
    location: Optional[str] = None
    description: Optional[str] = None


class CalendarSyncRequest(BaseModel):
    events: List[CalendarEvent]


@router.post("/calendar/sync")
async def sync_calendar(req: CalendarSyncRequest, _=Depends(verify_token)):
    """Upsert a batch of Samsung calendar events from the Android app."""
    try:
        count = upsert_events([ev.model_dump() for ev in req.events])
        return {"ok": True, "synced_count": count}
    except Exception as e:
        return {"ok": False, "synced_count": 0, "error": str(e)}
