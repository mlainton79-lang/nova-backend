"""Tony's Calendar endpoints."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from app.core.security import verify_token
from app.core.calendar_service import (
    get_upcoming_events, create_event, get_todays_schedule,
    get_calendar_auth_url
)
from app.core.gmail_service import get_all_accounts
from app.core.samsung_calendar import (
    format_events_for_prompt,
    get_calendar_diagnostics,
    get_read_status as get_samsung_calendar_read_status,
    infer_query_window,
    query_events,
)

router = APIRouter()

@router.get("/calendar/auth")
async def calendar_auth(email: str, _=Depends(verify_token)):
    """Get OAuth URL to grant Tony calendar access."""
    url = get_calendar_auth_url(email)
    return {"auth_url": url, "note": "Open this URL and grant access. Uses same token as Gmail if scopes match."}

@router.get("/calendar/today")
async def calendar_today(_=Depends(verify_token)):
    """Tony gets today's Samsung-synced device calendar schedule."""
    start, end, label = infer_query_window("today")
    try:
        events = query_events(start, end, limit=50, raise_on_error=True)
    except Exception:
        return {
            "source": "samsung",
            "ok": False,
            "schedule": "Calendar is unavailable right now.",
            "events": [],
            "count": 0,
        }
    return {
        "source": "samsung",
        "ok": True,
        "schedule": format_events_for_prompt(events, label),
        "events": events,
        "count": len(events),
    }


@router.get("/calendar/samsung/status")
async def calendar_samsung_status(_=Depends(verify_token)):
    """Read-only Samsung calendar sync status."""
    return get_samsung_calendar_read_status()


@router.get("/calendar/upcoming")
async def calendar_upcoming(days: int = 7, _=Depends(verify_token)):
    """Tony gets upcoming Samsung-synced device calendar events."""
    bounded_days = max(1, min(days, 730))
    start = datetime.now(ZoneInfo("Europe/London"))
    end = start + timedelta(days=bounded_days)
    try:
        events = query_events(start, end, limit=100, raise_on_error=True)
    except Exception:
        return {
            "source": "samsung",
            "ok": False,
            "days": bounded_days,
            "events": [],
            "count": 0,
            "error": "samsung_calendar_unavailable",
        }
    return {
        "source": "samsung",
        "ok": True,
        "days": bounded_days,
        "events": events,
        "count": len(events),
    }

@router.post("/calendar/create")
async def calendar_create(
    email: str, title: str, start: str, end: str,
    description: str = "", location: str = "",
    _=Depends(verify_token)
):
    """Tony creates a calendar event."""
    return await create_event(email, title, start, end, description, location)

@router.get("/calendar/test")
async def calendar_test(_=Depends(verify_token)):
    """Test calendar access."""
    accounts = get_all_accounts()
    results = {}
    for account in accounts:
        try:
            events = await get_upcoming_events(account, days=1)
            results[account] = {"ok": True, "events_today": len(events)}
        except Exception as e:
            results[account] = {"ok": False, "error": str(e)}
    return {"accounts": results}

@router.get("/calendar/samsung/diagnostics")
async def samsung_calendar_diagnostics(_=Depends(verify_token)):
    """Show compact Samsung calendar sync diagnostics."""
    return get_calendar_diagnostics()
